"""extract_hmb parsing edge cases, hysys_writer planning/read-back, backend.MockHysys, pid_extract two-pass parsing."""
import base64
import csv
import json
import sys
import types

import pytest

from hysys_bridge import backend, extract_hmb as X, hmb_check, hysys_writer as W, pid_extract as PX, spreadsheet
from hysys_bridge.ir import Flowsheet, Stream, Unit


# ---- parse_num --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("cell,want", [("12", 12.0), (" 12.5 ", 12.5), ("-3", -3.0), ("1,234.5", 1234.5), ("1e3", 1000.0),
                                       ("1.5E-2", 0.015), ("<5", 5.0), (">5", 5.0), ("~5", 5.0), ("≈ 5", 5.0), ("7.", 7.0)])
def test_parse_num_values(cell, want):
    assert X.parse_num(cell) == want


@pytest.mark.parametrize("cell", ["", "-", "—", "–", "n/a", "N/A", "na", "NIL", "none", None, "  "])
def test_parse_num_blank(cell):
    assert X.parse_num(cell) is None


@pytest.mark.parametrize("cell", ["abc", "1 2", "5%", "--5", "1.2.3"])
def test_parse_num_rejects_garbage(cell):
    with pytest.raises(ValueError, match="unparseable numeric cell"):
        X.parse_num(cell)


def test_label_unit_and_role():
    assert X._label_unit("Pressure (barg)") == ("pressure", "barg")
    assert X._label_unit("Water") == ("water", None)
    assert X._label_unit("Mass flow (kg/h)  ") == ("mass flow", "kg/h")
    assert X._role("temperature") == "T" and X._role("temp. out") == "T" and X._role("pressure drop") == "P"
    assert X._role("water") is None and X._role("") is None
    assert X._role("stream no.") == "id" and X._role("from") == "from" and X._role("to") == "to"
    assert X._role("vapor fraction") == "vf" and X._role("heat flow") == "H" and X._role("volumetric flow rate") == "vol"
    assert X._role("molar flow") == "mol" and X._role("total mass flow") == "mass"


def tbl(*extra, hdr=("Stream No.", "1", "2")):
    return [list(hdr), ["From", "-", "P-1"], ["To", "P-1", "-"], *map(list, extra)]


# ---- from_rows errors -------------------------------------------------------------------------------------
def test_missing_header_row():
    with pytest.raises(ValueError, match="no 'Stream No.' header row found"):
        X.from_rows([["a", "b"], ["c", "d"]])


def test_blank_and_duplicate_ids():
    with pytest.raises(ValueError, match="duplicate/blank stream ids"):
        X.from_rows([["Stream No.", "1", "1"]])
    with pytest.raises(ValueError, match="duplicate/blank stream ids"):
        X.from_rows([["Stream No.", "1", ""]])


def test_wrong_cell_count():
    with pytest.raises(ValueError, match=r"row 'Temperature \(C\)': 1 cells for 2 streams"):
        X.from_rows(tbl(["Temperature (C)", "25"]))


def test_pressure_needs_unit():
    with pytest.raises(ValueError, match="pressure needs an explicit unit"):
        X.from_rows(tbl(["Pressure", "5", "5"]))


def test_unparseable_value_in_property_row():
    with pytest.raises(ValueError, match="unparseable"):
        X.from_rows(tbl(["Temperature (C)", "hot", "25"]))


def test_unknown_units_raise():
    with pytest.raises(ValueError, match="unknown temperature unit"):
        X.from_rows(tbl(["Temperature (R)", "5", "5"]))
    with pytest.raises(ValueError, match="unknown/ambiguous pressure unit"):
        X.from_rows(tbl(["Pressure (psi)", "5", "5"]))
    with pytest.raises(ValueError, match="unknown mass-flow unit"):
        X.from_rows(tbl(["Mass flow (stone/h)", "5", "5"]))


# ---- from_rows behaviour ----------------------------------------------------------------------------------
def test_blank_rows_and_none_cells_are_dropped():
    fs = X.from_rows([[None, ""], *tbl(["Temperature (C)", "25", "30"]), []])
    assert fs.streams["1"].T_C == 25 and fs.streams["2"].T_C == 30


def test_default_units_when_label_has_none():
    fs = X.from_rows(tbl(["Temperature", "25", "30"], ["Mass flow", "100", "100"], ["Molar flow", "5", "5"],
                         ["Volume flow", "7", "7"], ["Enthalpy", "9", "9"]))
    s = fs.streams["1"]
    assert (s.T_C, s.mass_flow_kg_h, s.molar_flow_kmol_h, s.vol_flow_m3_h, s.checks["enthalpy_kJ_h"]) == (25, 100, 5, 7, 9)


def test_unit_conversion_and_sources():
    fs = X.from_rows(tbl(["Temperature (K)", "300", "310"], ["Pressure (barg)", "1", "2"], ["Mass flow (t/h)", "1", "2"],
                         ["Vapour fraction", "0.5", "1"], ["Heat flow (kW)", "1", "1"]), origin="f.csv", row0=10)
    s = fs.streams["1"]
    assert s.T_C == pytest.approx(300 - 273.15) and s.P_kPa == pytest.approx(201.325) and s.mass_flow_kg_h == 1000
    assert s.checks == {"vapour_fraction": 0.5, "enthalpy_kJ_h": 3600}
    assert s.source["T"] == "f.csv r13 'Temperature (K)' col '1'"        # row0 + index into filtered rows
    assert s.confidence["T"] == 1.0 and set(s.confidence) == {"T", "P", "mass", "vf", "H"}


def test_blank_property_cell_leaves_field_unset():
    fs = X.from_rows(tbl(["Temperature (C)", "25", "-"], ["Mass flow (kg/h)", "n/a", "5"]))
    assert fs.streams["2"].T_C is None and fs.streams["1"].mass_flow_kg_h is None
    assert "T" not in fs.streams["2"].source


def test_from_to_and_kinds_and_units_created():
    fs = X.from_rows(tbl())
    s1, s2 = fs.streams["1"], fs.streams["2"]
    assert (s1.src, s1.dst, s1.kind) == (None, "P-1", "feed") and (s2.src, s2.dst, s2.kind) == ("P-1", None, "product")
    assert fs.units["P-1"].type == "pump" and fs.units["P-1"].inlets == ["1"] and fs.units["P-1"].outlets == ["2"]


def test_intermediate_stream():
    fs = X.from_rows([["Stream No.", "1"], ["From", "P-1"], ["To", "E-1"]])
    assert fs.streams["1"].kind == "intermediate" and set(fs.units) == {"P-1", "E-1"}


@pytest.mark.parametrize("tag,typ", [("P-1", "pump"), ("E-100", "heater"), ("H-1", "heater"), ("C-1", "cooler"),
                                     ("V-1", "separator"), ("D-1", "separator"), ("K-1", "compressor"), ("T-1", "column"),
                                     ("MX-1", "mixer"), ("SP-1", "splitter"), ("FV-1", "valve"), ("PV-1", "valve"),
                                     ("LV-1", "valve"), ("R-1", "reactor"), ("p-1", "pump"), ("X-1", "unknown"),
                                     ("100", "unknown"), ("", "unknown")])
def test_guess_unit_type(tag, typ):
    assert X.guess_unit_type(tag) == typ


def comp_table(section, *rows):
    return [["Stream No.", "1", "2"], ["From", "-", "-"], ["To", "-", "-"], [section], *map(list, rows)]


@pytest.mark.parametrize("section,basis,scale", [
    ("Composition (mol%)", "mole", 100), ("Composition (mole %)", "mole", 100), ("Composition (mass%)", "mass", 100),
    ("Composition (wt%)", "mass", 100), ("Composition (weight fraction)", "mass", 1), ("Composition (mol fraction)", "mole", 1),
    ("Mole %", "mole", 100), ("Mass fraction", "mass", 1), ("Weight %", "mass", 100),
])
def test_composition_sections(section, basis, scale):
    fs = X.from_rows(comp_table(section, ["Water", "40", "60"]))
    s = fs.streams["1"]
    assert s.composition == {"Water": pytest.approx(40 / scale)} and s.composition_basis == basis
    assert s.source["x[Water]"].endswith("'Water' col '1'")
    assert fs.components == ["Water"]


def test_short_section_header_row_is_padded():
    rows = [["Stream No.", "1", "2"], ["From", "-", "-"], ["To", "-", "-"], ["Composition (mol%)"], ["A", "50", "50"]]
    assert X.from_rows(rows).streams["2"].composition == {"A": 0.5}


def test_short_nonblank_row_is_an_error():
    rows = [["Stream No.", "1", "2"], ["Temperature (C)", "25"]]
    with pytest.raises(ValueError, match="1 cells for 2 streams"):
        X.from_rows(rows)


def test_rows_before_any_section_are_ignored_but_numeric_property_row_ends_section():
    rows = comp_table("Composition (mol%)", ["A", "50", "50"], ["Temperature (C)", "25", "25"], ["Notes", "5", "5"])
    fs = X.from_rows(rows)
    assert fs.streams["1"].composition == {"A": 0.5}                      # 'Notes' came after a property row -> ignored
    plain = X.from_rows([["Stream No.", "1"], ["Notes", "xyz"]])
    assert plain.streams["1"].composition == {}


def test_blank_composition_cell_skipped_and_zero_kept():
    fs = X.from_rows(comp_table("Composition (mol%)", ["A", "0", "-"]))
    assert fs.streams["1"].composition == {"A": 0.0} and fs.streams["2"].composition == {}


def test_composition_unparseable_is_loud():
    with pytest.raises(ValueError, match="unparseable"):
        X.from_rows(comp_table("Composition (mol%)", ["A", "lots", "1"]))


def test_stream_header_aliases():
    fs = X.from_rows([["Stream Number", "a"], ["From", "-"], ["To", "-"]])
    assert list(fs.streams) == ["a"]


def test_from_csv_reads_utf8_bom(tmp_path):
    p = tmp_path / "h.csv"
    p.write_bytes("﻿Stream No.,1\nTemperature (°C),25\n".encode("utf-8"))
    fs = X.from_csv(str(p), name="n")
    assert fs.name == "n" and fs.streams["1"].T_C == 25 and fs.streams["1"].source["T"].startswith(str(p) + " r")


# ---- from_pdf (pdfplumber faked) --------------------------------------------------------------------------
class FakePage:
    def __init__(self, n, text, tables): self.page_number, self._t, self._tabs = n, text, tables
    def extract_text(self): return self._t
    def extract_tables(self): return self._tabs


def fake_pdfplumber(monkeypatch, pages):
    mod = types.ModuleType("pdfplumber")
    class PDF:
        def __init__(self): self.pages = pages
        def __enter__(self): return self
        def __exit__(self, *a): return False
    mod.open = lambda path: PDF()
    monkeypatch.setitem(sys.modules, "pdfplumber", mod)


def test_from_pdf_all_pages_concatenates_tables(monkeypatch):
    t1 = [["Stream No.", "1"], ["Temperature (C)", "25"]]
    fake_pdfplumber(monkeypatch, [FakePage(1, "txt", [t1]), FakePage(2, "txt", [])])
    fs = X.from_pdf("x.pdf", name="p")
    assert fs.name == "p" and fs.streams["1"].T_C == 25 and fs.streams["1"].source["T"].startswith("x.pdf")


def test_from_pdf_single_page_is_one_based(monkeypatch):
    good = [["Stream No.", "7"], ["Temperature (C)", "9"]]
    fake_pdfplumber(monkeypatch, [FakePage(1, "txt", [[["Stream No.", "1"]]]), FakePage(2, "txt", [good])])
    assert list(X.from_pdf("x.pdf", page=2).streams) == ["7"]
    assert list(X.from_pdf("x.pdf", page=1).streams) == ["1"]


def test_from_pdf_without_text_layer_requires_ocr(monkeypatch):
    fake_pdfplumber(monkeypatch, [FakePage(3, "", [])])
    with pytest.raises(ValueError, match=r"x\.pdf p3: no text layer \(scanned\?\) - OCR \+ review required"):
        X.from_pdf("x.pdf")


# ---- hysys_writer -----------------------------------------------------------------------------------------
def fs_for_writer():
    fs = Flowsheet(name="w", components=["A", "B"])
    for uid, t in (("P-1", "pump"), ("E-1", "heater"), ("V-1", "valve"), ("K-1", "compressor"), ("C-1", "cooler"), ("S-1", "separator")):
        fs.units[uid] = Unit(id=uid, type=t)
    fs.streams["f"] = Stream(id="f", kind="feed", dst="P-1", T_C=20, P_kPa=300, vol_flow_m3_h=4, molar_flow_kmol_h=3,
                             mass_flow_kg_h=2, composition={"A": 0.25, "B": 0.75}, source={"T": "cell-T"})
    for o, src, dst in (("a", "P-1", "E-1"), ("b", "E-1", "V-1"), ("c", "V-1", "K-1"), ("d", "K-1", "C-1"), ("e", "C-1", "S-1")):
        fs.streams[o] = Stream(id=o, src=src, dst=dst, T_C=50, P_kPa=900, mass_flow_kg_h=7)
    fs.streams["z"] = Stream(id="z", kind="feed", dst="S-1")                  # feed with nothing set
    fs.relink()
    return fs


def test_flow_spec_priority_mass_then_mol_then_vol():
    assert W.flow_spec(Stream(id="s", mass_flow_kg_h=1, molar_flow_kmol_h=2, vol_flow_m3_h=3)) == ("mass", 1)
    assert W.flow_spec(Stream(id="s", molar_flow_kmol_h=2, vol_flow_m3_h=3)) == ("mol", 2)
    assert W.flow_spec(Stream(id="s", vol_flow_m3_h=3)) == ("vol", 3)
    assert W.flow_spec(Stream(id="s", mass_flow_kg_h=0.0)) == ("mass", 0.0)       # zero is a value, not "missing"
    assert W.flow_spec(Stream(id="s")) is None


def test_plan_specs_independent_only():
    plan = W.plan_specs(fs_for_writer())
    assert plan == [("f", "T", 20), ("f", "P", 300), ("f", "mass", 2),            # feed: T, P and ONE flow basis
                    ("a", "P", 900),                                              # pump: P only
                    ("b", "T", 50), ("b", "P", 900),                              # heater: T and P
                    ("c", "P", 900), ("d", "P", 900),                             # valve / compressor: P only
                    ("e", "T", 50), ("e", "P", 900)]                              # cooler: T and P
    assert not any(s == "z" for s, _, _ in plan)


def test_plan_skips_outlet_pressure_when_unset():
    fs = fs_for_writer(); fs.streams["a"].P_kPa = None; fs.streams["b"].T_C = None; fs.streams["b"].P_kPa = None
    plan = W.plan_specs(fs)
    assert not any(s in ("a", "b") for s, _, _ in plan)


def test_write_rows_and_audit(tmp_path):
    fs = fs_for_writer(); be = backend.MockHysys()
    out = tmp_path / "a.csv"
    rows = W.write(fs, be, str(out))
    assert be.streams == set(fs.streams) and be.components == ["A", "B"]
    assert be.units["P-1"] == (["f"], ["a"])
    assert all(r.status == "OK" for r in rows)
    first = rows[0]
    assert (first.stream, first.prop, first.source, first.extracted, first.readback) == ("f", "T", "cell-T", 20, 20)
    assert rows[1].source == "derived"                                      # no recorded source
    assert [r.prop for r in rows if r.stream == "f"] == ["T", "P", "mass", "x[A]", "x[B]"]
    data = list(csv.reader(open(out)))
    assert data[0] == ["stream", "prop", "source", "extracted", "readback", "status"] and len(data) == len(rows) + 1
    assert data[1] == ["f", "T", "cell-T", "20", "20", "OK"]


def test_write_without_audit_creates_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    W.write(fs_for_writer(), backend.MockHysys())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("delta,status", [(0.0, "OK"), (1e-7, "OK"), (1e-3, "MISMATCH")])
def test_readback_tolerance_is_relative(delta, status):
    fs = fs_for_writer()
    be = backend.MockHysys(corrupt=lambda s, p, v: v + delta * max(abs(v), 1.0) if (s, p) == ("f", "P") else v)
    row = [r for r in W.write(fs, be) if (r.stream, r.prop) == ("f", "P")][0]
    assert row.status == status


def test_readback_none_is_mismatch():
    class Silent(backend.MockHysys):
        def get(self, sid, prop): return None
    assert {r.status for r in W.write(fs_for_writer(), Silent()) if r.prop in ("T", "P", "mass")} == {"MISMATCH"}


def test_small_values_use_absolute_floor_of_one():
    fs = Flowsheet(components=["A"])
    fs.streams["f"] = Stream(id="f", kind="feed", T_C=0.0, P_kPa=1, mass_flow_kg_h=1, composition={"A": 1.0})
    be = backend.MockHysys(corrupt=lambda s, p, v: v + 5e-7 if p == "T" else v)    # 5e-7 <= 1e-6 * max(|0|,1)
    assert W.write(fs, be)[0].status == "OK"
    be = backend.MockHysys(corrupt=lambda s, p, v: v + 2e-6 if p == "T" else v)
    assert W.write(fs, be)[0].status == "MISMATCH"


def test_composition_rows_mole_basis():
    fs = fs_for_writer()
    class Bad(backend.MockHysys):
        def get_comp(self, sid): return {"A": 0.25 + 1e-6, "B": 0.75}
    rows = {r.prop: r for r in W.write(fs, Bad()) if r.prop.startswith("x[")}
    assert rows["x[A]"].status == "MISMATCH" and rows["x[B]"].status == "OK"
    assert rows["x[A]"].readback == pytest.approx(0.25 + 1e-6)


def test_composition_rows_mass_basis_compares_after_solve_not_now():
    fs = fs_for_writer(); fs.streams["f"].composition_basis = "mass"
    class Mole(backend.MockHysys):
        def get_comp(self, sid): return {"A": 0.9, "B": 0.1}                # HYSYS answers on a mole basis
    rows = [r for r in W.write(fs, Mole()) if r.prop.startswith("x[")]
    assert [r.status for r in rows] == ["OK", "OK"] and [r.readback for r in rows] == [0.25, 0.75]
    class Missing(backend.MockHysys):
        def get_comp(self, sid): return {}
    rows = [r for r in W.write(fs, Missing()) if r.prop.startswith("x[")]
    assert [r.status for r in rows] == ["OK", "OK"]                          # mass-basis rows never fail read-back


def test_missing_composition_component_in_readback_is_mismatch():
    class Partial(backend.MockHysys):
        def get_comp(self, sid): return {"A": 0.25}
    rows = {r.prop: r for r in W.write(fs_for_writer(), Partial()) if r.prop.startswith("x[")}
    assert rows["x[B]"].status == "MISMATCH" and rows["x[B]"].readback is None and rows["x[A]"].status == "OK"


def test_feed_without_composition_writes_no_comp_rows():
    fs = fs_for_writer(); fs.streams["f"].composition = {}
    assert not any(r.prop.startswith("x[") for r in W.write(fs, backend.MockHysys()))


def test_unsupported_unit_type_raises_loudly():
    fs = fs_for_writer(); fs.units["S-1"].type = "column"
    with pytest.raises(KeyError, match="no HYSYS type for column"):
        W.write(fs, backend.MockHysys())


# ---- backend.MockHysys ------------------------------------------------------------------------------------
def test_mock_get_prefers_written_then_calc_then_none():
    m = backend.MockHysys(calc={("s", "T"): 99.0, ("s", "P"): 1.0})
    assert m.get("s", "T") == 99.0 and m.get("s", "X") is None
    m.set("s", "T", 5.0)
    assert m.get("s", "T") == 5.0 and m.get("s", "P") == 1.0
    m.set("s", "T", 0.0)
    assert m.get("s", "T") == 0.0                                            # a stored 0.0 must not fall through to calc


def test_mock_corrupt_hook_and_comp_copy():
    m = backend.MockHysys(corrupt=lambda s, p, v: v + 1)
    m.set("s", "T", 1.0); assert m.vals[("s", "T")] == 2.0
    x = {"A": 1.0}; m.set_comp("s", x, "mole"); x["A"] = 5
    assert m.get_comp("s") == {"A": 1.0} and m.get_comp("none") == {} and m.solve() is True


def test_mock_unit_registry():
    m = backend.MockHysys()
    for utype in backend.TYPE_MAP:
        m.add_unit("u", utype)
    with pytest.raises(KeyError):
        m.add_unit("u", "column")
    m.connect("u", ["a"], ["b"]); assert m.units["u"] == (["a"], ["b"])


def test_com_backend_refuses_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="needs Windows"):
        backend.HysysCOM()


# ---- hmb_check tolerance edges (with a calculating fake backend) ------------------------------------------
def hmb_fs():
    fs = Flowsheet(components=["A"])
    fs.streams["1"] = Stream(id="1", T_C=100.0, P_kPa=1000.0, mass_flow_kg_h=1000.0, molar_flow_kmol_h=10.0, vol_flow_m3_h=100.0,
                             checks={"vapour_fraction": 0.5}, composition={"A": 0.5})
    return fs


@pytest.mark.parametrize("prop,ref,got,ok", [
    ("T", 100.0, 100.5, True), ("T", 100.0, 100.5001 + 0.5, False),      # abs 0.5 + rel 0.5% of 100 = 1.0
    ("P", 1000.0, 1010.99, True), ("P", 1000.0, 1011.1, False),            # 1.0 + 1%
    ("mass", 1000.0, 1010.0, True), ("mass", 1000.0, 1010.5, False),
    ("mol", 10.0, 10.1, True), ("mol", 10.0, 10.2, False),
    ("vol", 100.0, 103.0, True), ("vol", 100.0, 103.5, False),
    ("vf", 0.5, 0.519, True), ("vf", 0.5, 0.521, False),
])
def test_hmb_tolerances(prop, ref, got, ok):
    fs = hmb_fs()
    d = {x.prop: x for x in hmb_check.check(fs, backend.MockHysys(calc={("1", prop): got}))}
    assert d[prop].ok is ok and d[prop].hmb == ref and d[prop].hysys == got


def test_hmb_missing_value_is_not_ok_and_none_refs_skipped():
    fs = hmb_fs(); fs.streams["1"].T_C = None
    d = {x.prop for x in hmb_check.check(fs, backend.MockHysys())}
    assert "T" not in d and {"P", "mass", "mol", "vol", "vf"} <= d
    assert all(not x.ok for x in hmb_check.check(fs, backend.MockHysys()))


def test_hmb_composition_only_for_mole_basis():
    fs = hmb_fs()
    class C(backend.MockHysys):
        def get_comp(self, sid): return {"A": 0.5 + 0.0071}
    assert [x.ok for x in hmb_check.check(fs, C()) if x.prop == "x[A]"] == [False]    # tolerance is 0.002 + 1% of 0.5 = 0.007
    class C2(backend.MockHysys):
        def get_comp(self, sid): return {"A": 0.5 + 0.0069}
    assert [x.ok for x in hmb_check.check(fs, C2()) if x.prop == "x[A]"] == [True]
    fs.streams["1"].composition_basis = "mass"
    assert not any(x.prop == "x[A]" for x in hmb_check.check(fs, C()))


# ---- spreadsheet.Prop -------------------------------------------------------------------------------------
def test_prop_str():
    assert str(spreadsheet.Prop("s1", "T", 25.0, 30.5, False)) == "s1|T: wrote 25, HYSYS reports 30.5"
    assert str(spreadsheet.Prop("s1", "P", 1234567.0, None, False)) == "s1|P: wrote 1.23457e+06, HYSYS reports None"


# ---- pid_extract ------------------------------------------------------------------------------------------
def scripted(units, streams):
    replies = [json.dumps({"units": units}), json.dumps({"streams": streams})]
    calls = []
    def ask(prompt):
        calls.append(prompt); return replies[len(calls) - 1]
    ask.calls = calls
    return ask


def test_json_extraction_from_chatty_reply():
    assert PX._json('Sure! {"a": {"b": 1}} hope that helps') == {"a": {"b": 1}}
    with pytest.raises(ValueError, match="no JSON in model reply: 'no braces here'"):
        PX._json("no braces here")


def test_two_pass_builds_draft_topology():
    ask = scripted([{"id": "P-1", "type": "pump"}, {"id": "E-1", "type": "bogus"}, {"id": "U1", "type": "heater"}],
                   [{"id": "1", "src": None, "dst": "P-1"}, {"id": "2", "src": "P-1", "dst": "E-1"}, {"id": "3", "src": "E-1", "dst": None}])
    fs = PX.parse_two_pass(ask, name="n")
    assert fs.name == "n"
    assert fs.units["P-1"].type == "pump" and fs.units["E-1"].type == "heater"       # invalid type -> tag guess
    assert fs.units["U1"].type == "heater"
    assert all(u.flags == ["needs-signoff"] for u in fs.units.values())
    assert [fs.streams[i].kind for i in "123"] == ["feed", "intermediate", "product"]
    assert fs.units["P-1"].inlets == ["1"] and fs.units["P-1"].outlets == ["2"]
    assert len(ask.calls) == 2 and ask.calls[0] == PX.P1 and "['P-1', 'E-1', 'U1']" in ask.calls[1]


def test_untyped_unit_falls_back_to_tag_guess_then_unknown():
    fs = PX.parse_two_pass(scripted([{"id": "K-1"}, {"id": "ZZ"}], []))
    assert fs.units["K-1"].type == "compressor" and fs.units["ZZ"].type == "unknown"


def test_duplicate_unit_ids_rejected():
    with pytest.raises(ValueError, match="duplicate unit ids from model"):
        PX.parse_two_pass(scripted([{"id": "A"}, {"id": "A"}], []))


@pytest.mark.parametrize("end", ["src", "dst"])
def test_hallucinated_endpoint_rejected(end):
    s = {"id": "1", "src": None, "dst": None}; s[end] = "GHOST"
    with pytest.raises(ValueError, match=f"stream 1: {end}='GHOST' not a known unit"):
        PX.parse_two_pass(scripted([{"id": "A"}], [s]))


def test_duplicate_stream_ids_rejected():
    with pytest.raises(ValueError, match="duplicate stream id 1"):
        PX.parse_two_pass(scripted([{"id": "A"}], [{"id": "1", "dst": "A"}, {"id": "1", "src": "A"}]))


def test_extract_names_flowsheet_after_file_basename():
    fs = PX.extract("/a/b/drawing.png", ask=scripted([{"id": "A"}], []))
    assert fs.name == "drawing.png"
    assert PX.extract("plain.png", ask=scripted([], [])).name == "plain.png"


def test_extract_default_asker_receives_path_and_page(monkeypatch):
    seen = []
    monkeypatch.setattr(PX, "anthropic_ask", lambda path, page=1: seen.append((path, page)) or scripted([{"id": "A"}], []))
    PX.extract("d.png", page=3)
    assert seen == [("d.png", 3)]


def test_image_b64_png_and_jpeg(tmp_path):
    png, jpg, other = tmp_path / "a.PNG", tmp_path / "a.jpg", tmp_path / "a.gif"
    for p in (png, jpg, other): p.write_bytes(b"\x01\x02")
    assert PX._image_b64(str(png)) == (base64.b64encode(b"\x01\x02").decode(), "image/png")
    assert PX._image_b64(str(jpg))[1] == "image/jpeg" and PX._image_b64(str(other))[1] == "image/jpeg"


def test_image_b64_pdf_uses_requested_page_and_dpi(monkeypatch):
    seen = {}
    class Pix:
        def tobytes(self, fmt): seen["fmt"] = fmt; return b"PNGDATA"
    class Page:
        def get_pixmap(self, dpi): seen["dpi"] = dpi; return Pix()
    class Doc:
        def __getitem__(self, i): seen["idx"] = i; return Page()
    mod = types.ModuleType("fitz"); mod.open = lambda p: seen.setdefault("path", p) and Doc() or Doc()
    monkeypatch.setitem(sys.modules, "fitz", mod)
    b64, mt = PX._image_b64("x.PDF", page=3, dpi=150)
    assert (b64, mt) == (base64.b64encode(b"PNGDATA").decode(), "image/png")
    assert seen == {"path": "x.PDF", "idx": 2, "dpi": 150, "fmt": "png"}


def test_merge_values_copies_numbers_and_reports_differences():
    topo = Flowsheet()
    topo.units["P"] = Unit(id="P", type="pump"); topo.units["E"] = Unit(id="E", type="heater")
    topo.streams["1"] = Stream(id="1", dst="P", kind="feed")
    topo.streams["2"] = Stream(id="2", src="P", dst="E")
    topo.streams["9"] = Stream(id="9", src="E")
    hmb = Flowsheet(components=["A"])
    hmb.streams["1"] = Stream(id="1", dst="P", T_C=25, P_kPa=500, mass_flow_kg_h=10, molar_flow_kmol_h=1, vol_flow_m3_h=2,
                              composition={"A": 1.0}, composition_basis="mass", checks={"vapour_fraction": 0}, source={"T": "s"},
                              confidence={"T": 1.0})
    hmb.streams["2"] = Stream(id="2", src="P", dst="X")                      # connectivity differs
    hmb.streams["5"] = Stream(id="5", src="P", dst="E")                      # not on the P&ID
    notes = PX.merge_values(topo, hmb)
    assert notes == ["stream 2: P&ID P->E vs H&MB P->X", "stream 5 in H&MB but not on P&ID", "stream 9 on P&ID but not in H&MB"]
    s = topo.streams["1"]
    assert (s.T_C, s.P_kPa, s.mass_flow_kg_h, s.molar_flow_kmol_h, s.vol_flow_m3_h) == (25, 500, 10, 1, 2)
    assert s.composition == {"A": 1.0} and s.composition_basis == "mass" and s.checks == {"vapour_fraction": 0}
    assert s.source == {"T": "s"} and s.confidence == {"T": 1.0}
    assert topo.components == ["A"]
    assert (topo.streams["1"].src, topo.streams["1"].dst) == (None, "P")     # topology itself is never overwritten


def test_merge_values_blank_hmb_connectivity_is_not_a_conflict():
    topo = Flowsheet(); topo.streams["1"] = Stream(id="1", src="A", dst="B")
    hmb = Flowsheet(); hmb.streams["1"] = Stream(id="1")                     # H&MB gave no From/To
    assert PX.merge_values(topo, hmb) == []
    hmb.streams["1"].src = "A"
    assert PX.merge_values(topo, hmb) == ["stream 1: P&ID A->B vs H&MB A->None"]
