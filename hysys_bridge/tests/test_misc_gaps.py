"""Small remaining gaps: reconcile warnings, spreadsheet solve timeout, DEXPI unit params, pid_eval/pydexpi edges."""
import json
import os
import runpy
import sys
import warnings

import pytest

from hysys_bridge import dexpi_export, dexpi_process, extract_hmb, normalize, pid_eval, pid_reconcile, spreadsheet
from hysys_bridge.ir import Flowsheet, Stream, Unit

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample", "hmb.csv")


# ---- pid_reconcile ----------------------------------------------------------------------------------------
def line(*units, streams):
    fs = Flowsheet()
    for uid, t in units: fs.units[uid] = Unit(id=uid, type=t)
    for sid, a, b in streams: fs.streams[sid] = Stream(id=sid, src=a, dst=b)
    fs.relink()
    return fs


def texts(issues): return [str(i) for i in issues]


def test_isolated_unit_warns_or_is_removed():
    fs = line(("P-1", "pump"), ("E-1", "heater"), ("V-1", "separator"), streams=[("1", None, "P-1"), ("2", "P-1", None)])
    issues, acts = pid_reconcile.reconcile(fs)
    assert "[WARN] E-1: isolated unit: no streams attached" in texts(issues) and acts == [] and "E-1" in fs.units
    issues, acts = pid_reconcile.reconcile(fs, fix=True)
    assert acts == ["removed isolated unit E-1", "removed isolated unit V-1"] and set(fs.units) == {"P-1"}
    assert not any("isolated" in t for t in texts(issues))


def test_tag_suggesting_other_type_warns_but_unknown_does_not():
    fs = line(("P-1", "heater"), ("X-9", "pump"), ("E-1", "unknown"), streams=[("1", None, "P-1"), ("2", "P-1", "X-9"), ("3", "X-9", "E-1"), ("4", "E-1", None)])
    t = texts(pid_reconcile.reconcile(fs)[0])
    assert "[WARN] P-1: tag suggests pump but type is heater" in t
    assert not any(x.startswith("[WARN] X-9: tag") or x.startswith("[WARN] E-1: tag") for x in t)


def test_parallel_streams_warn_except_for_splitting_units():
    fs = line(("P-1", "pump"), ("E-1", "heater"), streams=[("1", None, "P-1"), ("2", "P-1", "E-1"), ("3", "P-1", "E-1"), ("4", "E-1", None)])
    t = texts(pid_reconcile.reconcile(fs)[0])
    assert "[WARN] 2,3: 2 parallel streams P-1->E-1: possible double detection" in t
    for typ in ("separator", "column", "splitter"):
        fs = line(("V-1", typ), ("E-1", "heater"), streams=[("1", None, "V-1"), ("2", "V-1", "E-1"), ("3", "V-1", "E-1"), ("4", "E-1", None)])
        assert not any("parallel" in x for x in texts(pid_reconcile.reconcile(fs)[0]))


# ---- spreadsheet solve timeout ----------------------------------------------------------------------------
class Solver:
    CanSolve = False
    def __init__(self, busy_for): self.n = busy_for
    @property
    def IsSolving(self):
        self.n -= 1
        return self.n >= 0


def sheet_backend(solver, timeout):
    lay = spreadsheet.build_layout(extract_hmb.from_csv(SAMPLE))
    return spreadsheet.SpreadsheetBackend(lay, None, None, solver, timeout_s=timeout)


def test_solve_times_out_and_sets_cansolve(monkeypatch):
    monkeypatch.setattr(spreadsheet.time, "sleep", lambda s: None)
    sv = Solver(10 ** 9)
    assert sheet_backend(sv, 0.0).solve() is False and sv.CanSolve is True      # solver never finishes


def test_solve_returns_true_when_solver_finishes(monkeypatch):
    slept = []
    monkeypatch.setattr(spreadsheet.time, "sleep", lambda s: slept.append(s))
    assert sheet_backend(Solver(3), 1000.0).solve() is True and slept == [0.05, 0.05, 0.05]


# ---- DEXPI unit parameters ---------------------------------------------------------------------------------
def test_unit_params_roundtrip_through_proteus_xml(tmp_path):
    fs = extract_hmb.from_csv(SAMPLE); normalize.normalize(fs)
    fs.units["E-100"].params = {"duty_kW": 12.5, "dp_kPa": 0.0}
    xml = dexpi_export.export(fs)
    back = dexpi_export.load(xml)
    assert back.units["E-100"].params == {"duty_kW": 12.5, "dp_kPa": 0.0}
    assert back.units["MX-100"].params == {}


# ---- pid_eval CLI -------------------------------------------------------------------------------------------
def test_pid_eval_main_prints_score(tmp_path, monkeypatch, capsys):
    fs = extract_hmb.from_csv(SAMPLE)
    a, b = tmp_path / "a.json", tmp_path / "b.json"; fs.to_json(str(a)); fs.to_json(str(b))
    for extra, mode in (([], "id"), (["structure"], "structure")):
        monkeypatch.setattr(sys, "argv", ["pid_eval", str(a), str(b), *extra])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            runpy.run_module("hysys_bridge.pid_eval", run_name="__main__")
        assert capsys.readouterr().out.startswith(f"[matching={mode}] nodes P/R/F1 1.00/1.00/1.00")


# ---- dexpi_process without / with pydexpi ---------------------------------------------------------------------
def test_missing_pydexpi_is_a_clean_exit(monkeypatch):
    monkeypatch.setitem(sys.modules, "pydexpi", None)
    for name in [m for m in sys.modules if m.startswith("pydexpi.")]:
        monkeypatch.setitem(sys.modules, name, None)
    with pytest.raises(SystemExit, match="dexpi_process needs pydexpi"):
        dexpi_process.build(Flowsheet())


def _legacy_streams(tmp_path):
    pytest.importorskip("pydexpi")
    fs = extract_hmb.from_csv(SAMPLE); normalize.normalize(fs)
    model = dexpi_process.build(fs)
    C, J = dexpi_process._pydexpi()
    unit = C.RatioUnit("Fraction")
    for st in model.conceptualModel.processConnections:
        mst = st.materialStateReference.state
        if mst.composition is None or not mst.composition.moleFractions: continue
        vec = mst.composition.moleFractions[0].value.values
        # one quantity per component: the layout read_streams calls "older files of ours"
        mst.composition = C.Composition(moleFractions=[C.QualifiedValue(case="design", value=C.PhysicalQuantity(value=v, unit=unit)) for v in vec])
    J().save(model, str(tmp_path), "legacy.json")
    return dexpi_process.read_streams(str(tmp_path), "legacy.json")


def test_read_streams_vector_composition_yields_numbers(tmp_path):
    pytest.importorskip("pydexpi")
    fs = extract_hmb.from_csv(SAMPLE); normalize.normalize(fs)
    dexpi_process.export_json(fs, str(tmp_path), "v.json")
    back = dexpi_process.read_streams(str(tmp_path), "v.json")
    assert back["3"]["composition"] == {"Ethanol": pytest.approx(0.334), "Water": pytest.approx(0.666)}
    assert back["1"]["composition"] == {"Water": pytest.approx(1.0)} and back["1"]["basis"] == "mole"


def test_read_streams_legacy_per_component_composition_components_and_basis(tmp_path):
    back = _legacy_streams(tmp_path)
    assert set(back["3"]["composition"]) == {"Ethanol", "Water"} and back["3"]["basis"] == "mole"


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="read_streams legacy branch stores q.value, which is a PhysicalQuantity object, not the number "
                          "(the vector branch correctly yields floats) and the `if q.value` zero filter is always true; should use q.value.value")
def test_read_streams_legacy_per_component_composition_values_are_numbers(tmp_path):
    back = _legacy_streams(tmp_path)
    assert back["3"]["composition"] == {"Ethanol": pytest.approx(0.334), "Water": pytest.approx(0.666)}
    assert back["1"]["composition"] == {"Water": pytest.approx(1.0)}          # zero fractions dropped, as in the vector branch
