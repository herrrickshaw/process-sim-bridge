"""mcp_server: tool gating, live/COM paths (faked), error mapping, and the stdio loop. Never touches HYSYS."""
import io
import json
import os
import runpy
import sys
import types
import warnings

import pytest

from hysys_bridge import backend, dexpi_export, dexpi_process, extract_hmb, mcp_server as M, pid_extract, spreadsheet
from hysys_bridge.backend import MockHysys
from hysys_bridge.ir import Flowsheet, Stream, Unit

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample", "hmb.csv")
CSV_TEXT = open(SAMPLE, encoding="utf-8").read()


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(M, "SESSIONS", {})
    monkeypatch.delenv("HYSYS_LIVE", raising=False)
    monkeypatch.delenv("HYSYS_BRIDGE_DEBUG", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def rpc(method, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "method": method}
    if mid is not None: msg["id"] = mid
    if params is not None: msg["params"] = params
    return M.handle(msg)


def call(tool, **args):
    r = rpc("tools/call", {"name": tool, "arguments": args})["result"]
    txt = r["content"][0]["text"]
    return r["isError"], (txt if r["isError"] else json.loads(txt))


@pytest.fixture
def loaded():
    err, _ = call("load_hmb", name="h", csv_text=CSV_TEXT)
    assert not err


# ---- status -----------------------------------------------------------------------------------------------
def test_status_without_pywin32(monkeypatch):
    monkeypatch.setitem(sys.modules, "win32com", None)               # makes `import win32com.client` raise ImportError
    monkeypatch.setitem(sys.modules, "win32com.client", None)
    _, r = call("status")
    assert r["version"] == "0.1.0" and r["pywin32"] is False and r["HYSYS_LIVE"] is False
    assert r["live_writes_possible"] is False and r["sessions"] == [] and r["platform"] == sys.platform


def test_status_live_possible_needs_windows_env_and_pywin32(monkeypatch):
    pkg = types.ModuleType("win32com"); sub = types.ModuleType("win32com.client"); pkg.client = sub
    monkeypatch.setitem(sys.modules, "win32com", pkg); monkeypatch.setitem(sys.modules, "win32com.client", sub)
    monkeypatch.setenv("HYSYS_LIVE", "1")
    monkeypatch.setattr(sys, "platform", "win32")
    _, r = call("status")
    assert r["pywin32"] is True and r["HYSYS_LIVE"] is True and r["live_writes_possible"] is True
    monkeypatch.setattr(sys, "platform", "linux")
    assert call("status")[1]["live_writes_possible"] is False        # not Windows
    monkeypatch.setattr(sys, "platform", "win32"); monkeypatch.setenv("HYSYS_LIVE", "0")
    assert call("status")[1]["live_writes_possible"] is False        # env must be exactly "1"
    monkeypatch.setenv("HYSYS_LIVE", "1")
    call("load_hmb", name="b", csv_text=CSV_TEXT); call("load_hmb", name="a", csv_text=CSV_TEXT)
    assert call("status")[1]["sessions"] == ["a", "b"]               # sorted


# ---- loading ----------------------------------------------------------------------------------------------
def test_load_hmb_inline_csv_and_fluid_package():
    err, r = call("load_hmb", name="h", csv_text=CSV_TEXT, fluid_package="NRTL")
    assert not err and r["fluid_package"] == "NRTL" and r["session"] == "h"
    assert r["streams"] == {"1": "FEED -> MX-100", "2": "FEED -> MX-100", "3": "MX-100 -> E-100", "4": "E-100 -> PRODUCT"}
    assert r["units"] == {"MX-100": "mixer", "E-100": "heater"} and r["components"] == ["Ethanol", "Water"]
    assert M.SESSIONS["h"].streams["1"].source["T"].startswith("inline r")
    assert call("load_hmb", name="d", csv_text=CSV_TEXT)[1]["fluid_package"] == "Peng-Robinson"


def test_load_hmb_csv_text_wins_over_path():
    err, r = call("load_hmb", name="h", csv_text=CSV_TEXT, path="/does/not/exist.csv")
    assert not err and "1" in r["streams"]


def test_load_hmb_path_by_extension(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(extract_hmb, "from_pdf", lambda p, page=None: seen.setdefault("pdf", (p, page)) and extract_hmb.from_csv(SAMPLE))
    pdf = tmp_path / "r.PDF"; pdf.write_bytes(b"%PDF")
    assert not call("load_hmb", name="p", path=str(pdf), page=2)[0]
    assert seen["pdf"] == (str(pdf), 2)
    csvp = tmp_path / "r.csv"; csvp.write_text(CSV_TEXT)
    assert not call("load_hmb", name="c", path=str(csvp))[0] and M.SESSIONS["c"].streams["1"].source["T"].startswith(str(csvp))


def test_load_hmb_rejects_other_extensions_and_missing_file(tmp_path):
    p = tmp_path / "x.xml"; p.write_text("<a/>")
    err, msg = call("load_hmb", name="h", path=str(p))
    assert err and msg.startswith("ValueError: file type .xml not allowed here; allowed: ['.csv', '.pdf']")
    err, msg = call("load_hmb", name="h", path=str(tmp_path / "nope.csv"))
    assert err and msg.startswith("FileNotFoundError:")
    err, msg = call("load_hmb", name="h", path=str(tmp_path / "noext"))
    assert err and "(none)" in msg


def test_load_hmb_systemexit_message_is_reported_without_type(monkeypatch, tmp_path):
    def boom(p, page=None): raise SystemExit("pip install pdfplumber")
    monkeypatch.setattr(extract_hmb, "from_pdf", boom)
    p = tmp_path / "r.pdf"; p.write_bytes(b"x")
    assert call("load_hmb", name="h", path=str(p)) == (True, "pip install pdfplumber")


def test_load_flowsheet_json_and_dexpi_paths(tmp_path, loaded):
    p = tmp_path / "f.json"; M.SESSIONS["h"].to_json(str(p))
    err, r = call("load_flowsheet_json", name="j", path=str(p))
    assert not err and r["session"] == "j" and M.SESSIONS["j"] == M.SESSIONS["h"]
    assert call("load_flowsheet_json", name="j", path=str(tmp_path / "f.xml"))[0]       # wrong extension
    x = tmp_path / "f.xml"; dexpi_export.export(M.SESSIONS["h"], str(x))
    err, r = call("load_dexpi", name="d", path=str(x))
    assert not err and set(r["units"]) == {"MX-100", "E-100"}


# ---- inspection tools -------------------------------------------------------------------------------------
def test_unknown_session_message(loaded):
    err, msg = call("summarize", name="zzz")
    assert err and msg == "KeyError: \"no session 'zzz'; loaded: ['h']\""
    M.SESSIONS.clear()
    assert "loaded: none" in call("summarize", name="zzz")[1]


def test_normalize_validate_plan(loaded):
    err, r = call("normalize", name="h")
    assert not err and r["actions"] == [] and r["session"] == "h"
    err, v = call("validate", name="h")
    assert v == {"errors": [], "warnings": [], "blocks_hysys_write": False}
    M.SESSIONS["h"].streams["1"].composition = {"Water": 0.99, "Ethanol": 0.0}
    v = call("validate", name="h")[1]
    assert v["warnings"] == ["[WARN] 1: composition sums to 0.99000 (basis=mole)"] and v["errors"] == [] and v["blocks_hysys_write"] is False
    M.SESSIONS["h"].streams["1"].composition = {"Water": 0.5, "Ethanol": 0.0}
    v = call("validate", name="h")[1]
    assert v["errors"] == ["[ERROR] 1: composition sums to 0.50000 (basis=mole)"] and v["blocks_hysys_write"] is True
    plan = call("plan_specs", name="h")[1]
    assert plan["count"] == 8 and plan["specs"][0] == {"stream": "1", "prop": "T", "value": 25.0}


def test_reconcile_fix_flag(loaded):
    fs = M.SESSIONS["h"]
    fs.units["LOOP"] = Unit(id="LOOP", type="pump")
    fs.streams["9"] = Stream(id="9", src="LOOP", dst="LOOP")
    err, r = call("reconcile", name="h")
    assert r["auto_fixes_applied"] == [] and any("self-loop on LOOP" in f for f in r["findings"]) and "9" in fs.streams
    err, r = call("reconcile", name="h", fix=True)
    assert r["auto_fixes_applied"] == ["removed self-loop stream 9 on LOOP", "removed isolated unit LOOP"] and "9" not in fs.streams


def test_score_modes_and_caveat(loaded):
    M.SESSIONS["t"] = M.SESSIONS["h"]
    r = call("score", name="h", truth="t", mode="structure")[1]
    assert r["score"].startswith("[matching=structure] nodes P/R/F1 1.00/1.00/1.00") and r["caveat"].startswith("P/R/F1 on a graph")
    assert call("score", name="h", truth="t")[1]["score"].startswith("[matching=id] ")        # default mode
    assert call("score", name="h", truth="nope")[0] is True


def test_merge_pid_hmb_reports_conflicts(loaded):
    topo = Flowsheet()
    topo.units["MX-100"] = Unit(id="MX-100", type="mixer")
    topo.streams["3"] = Stream(id="3", src="MX-100", dst="ZZ")
    M.SESSIONS["t"] = topo
    err, r = call("merge_pid_hmb", topology="t", hmb="h")
    assert "stream 3: P&ID MX-100->ZZ vs H&MB MX-100->E-100" in r["conflicts_and_gaps"]
    assert "stream 1 in H&MB but not on P&ID" in r["conflicts_and_gaps"] and r["session"] == "t"


# ---- write_to_hysys: mock -----------------------------------------------------------------------------------
def test_write_dry_plan_counts_specs(loaded):
    err, r = call("write_to_hysys", name="h")
    assert r == {"written": False, "reason": "dry plan only: pass confirm=true to write", "specs": 8}


def test_write_with_audit_csv_and_overwrite_guard(loaded, tmp_path):
    p = tmp_path / "audit.csv"
    err, r = call("write_to_hysys", name="h", confirm=True, audit_csv=str(p))
    assert not err and r["audit_csv"] == str(p) and r["values_written"] == 12 and p.exists()
    assert r["solved"] is True and r["hmb_disagreement_count"] == 12 and len(r["hmb_disagreements"]) == 12
    assert r["warning"] == "mock backend performs no calculation: disagreements are expected"
    err, msg = call("write_to_hysys", name="h", confirm=True, audit_csv=str(p))
    assert err and "exists; pass overwrite=true" in msg
    assert not call("write_to_hysys", name="h", confirm=True, audit_csv=str(p), overwrite=True)[0]
    assert call("write_to_hysys", name="h", confirm=True, audit_csv=str(tmp_path / "a.txt"))[0]   # extension not allowed


def test_write_audit_guard_runs_before_any_backend_call(loaded, tmp_path, monkeypatch):
    made = []
    monkeypatch.setattr(M, "MockHysys", lambda: made.append(1) or MockHysys())
    (tmp_path / "a.csv").write_text("x")
    assert call("write_to_hysys", name="h", confirm=True, audit_csv=str(tmp_path / "a.csv"))[0]
    assert (tmp_path / "a.csv").read_text() == "x"


def test_write_readback_mismatch_stops_before_solve(loaded, monkeypatch):
    monkeypatch.setattr(M, "MockHysys", lambda: MockHysys(corrupt=lambda s, p, v: v + 1 if p == "T" else v))
    err, r = call("write_to_hysys", name="h", confirm=True)
    assert r["next"] == "fix mismatches before solving" and len(r["readback_mismatches"]) == 3
    assert "solved" not in r and r["saved"] is False and r["backend"] == "mock"
    assert r["readback_mismatches"][0]["status"] == "MISMATCH" and r["readback_mismatches"][0]["stream"] == "1"


def test_write_mismatch_list_capped_at_50(loaded, monkeypatch):
    fs = M.SESSIONS["h"]
    for i in range(60):
        sid = f"x{i}"; fs.streams[sid] = Stream(id=sid, kind="feed", T_C=1.0, P_kPa=1.0, mass_flow_kg_h=1.0, composition={"Water": 1.0})
    monkeypatch.setattr(M, "MockHysys", lambda: MockHysys(corrupt=lambda s, p, v: v + 1))
    monkeypatch.setattr(M._validate, "validate", lambda fs: [])
    r = call("write_to_hysys", name="h", confirm=True)[1]
    assert len(r["readback_mismatches"]) == 50


def test_write_unsolved_has_no_hmb_section(loaded, monkeypatch):
    class NoSolve(MockHysys):
        def solve(self): return False
    monkeypatch.setattr(M, "MockHysys", NoSolve)
    r = call("write_to_hysys", name="h", confirm=True)[1]
    assert r["solved"] is False and "hmb_disagreements" not in r and "warning" not in r


def test_write_hmb_disagreement_lists_capped_at_100(loaded, monkeypatch):
    monkeypatch.setattr(M.hmb_check, "check", lambda fs, be: [types.SimpleNamespace(ok=False, i=i) for i in range(150)])
    monkeypatch.setattr(M.dataclasses, "asdict", lambda d: {"i": getattr(d, "i", None), "status": "OK", "stream": "s"})
    r = call("write_to_hysys", name="h", confirm=True)[1]
    assert r["hmb_disagreement_count"] == 150 and len(r["hmb_disagreements"]) == 100


# ---- write_to_hysys: live COM (faked) -----------------------------------------------------------------------
class FakeCOM(MockHysys):
    made = []
    def __init__(self, visible=False, open_path=None, use_active=False):
        super().__init__(); self.args = (visible, open_path, use_active); FakeCOM.made.append(self)


def test_live_write_uses_com_backend_with_named_case(loaded, tmp_path, monkeypatch):
    FakeCOM.made = []
    monkeypatch.setattr(backend, "HysysCOM", FakeCOM)
    monkeypatch.setenv("HYSYS_LIVE", "1")
    case = tmp_path / "plant.hsc"; case.write_bytes(b"")
    err, r = call("write_to_hysys", name="h", confirm=True, live=True, case_path=str(case), visible=True)
    assert not err and r["backend"] == "HYSYS" and r["saved"] is False
    assert FakeCOM.made[0].args == (True, str(case), False)
    assert "warning" not in r                                         # the mock-only caveat is not shown for live runs


def test_live_write_use_active(loaded, monkeypatch):
    FakeCOM.made = []
    monkeypatch.setattr(backend, "HysysCOM", FakeCOM)
    monkeypatch.setenv("HYSYS_LIVE", "1")
    assert not call("write_to_hysys", name="h", confirm=True, live=True, use_active=True)[0]
    assert FakeCOM.made[0].args == (False, None, True)


def test_live_case_path_must_be_hsc_and_exist(loaded, tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "HysysCOM", FakeCOM); monkeypatch.setenv("HYSYS_LIVE", "1")
    other = tmp_path / "x.csv"; other.write_text("")
    err, msg = call("write_to_hysys", name="h", confirm=True, live=True, case_path=str(other))
    assert err and "allowed: ['.hsc']" in msg
    err, msg = call("write_to_hysys", name="h", confirm=True, live=True, case_path=str(tmp_path / "n.hsc"))
    assert err and msg.startswith("FileNotFoundError")


def test_live_flag_is_ignored_in_dry_plan(loaded):
    assert call("write_to_hysys", name="h", live=True)[1]["written"] is False        # confirm gate comes first


# ---- write_to_hysys: spreadsheet method -----------------------------------------------------------------------
def test_spreadsheet_mock_run_with_audit_and_units(loaded, tmp_path):
    p = tmp_path / "s.csv"
    err, r = call("write_to_hysys", name="h", confirm=True, method="spreadsheet", audit_csv=str(p), units={"T": "K"})
    assert not err and r["units"]["T"] == "K" and r["cells_written"] == 12 and p.exists()
    assert r["propagation_ok"] is True and r["propagation_failures"] == [] and "hint" not in r
    assert r["warning"].startswith("mock case imitates the links")
    assert "hmb_disagreement_count" in r
    err, msg = call("write_to_hysys", name="h", confirm=True, method="spreadsheet", audit_csv=str(p))
    assert err and "overwrite" in msg


def test_spreadsheet_mismatch_and_propagation_failure_paths(loaded, monkeypatch):
    class BadCase(spreadsheet.MockSheetCase):
        def backend(self):
            be = super().backend()
            real = be.set
            be.set = lambda sid, prop, v: real(sid, prop, v + 1 if prop == "P" else v)     # breaks read-back of P
            return be
    monkeypatch.setattr(spreadsheet, "MockSheetCase", BadCase)
    r = call("write_to_hysys", name="h", confirm=True, method="spreadsheet")[1]
    assert r["next"] == "fix mismatches before solving" and "solved" not in r and r["readback_mismatches"]
    assert r["method"] == "spreadsheet" and r["saved"] is False


def test_spreadsheet_propagation_failure_reports_hint(loaded, monkeypatch):
    bad = spreadsheet.Prop("1", "T", 1.0, 2.0, False)
    monkeypatch.setattr(spreadsheet, "verify_propagation", lambda fs, be: [bad] * 150)
    r = call("write_to_hysys", name="h", confirm=True, method="spreadsheet")[1]
    assert r["propagation_ok"] is False and len(r["propagation_failures"]) == 100
    assert r["propagation_failures"][0] == "1|T: wrote 1, HYSYS reports 2.0" and r["hint"].startswith("unlinked cell")


def test_spreadsheet_unsolved(loaded, monkeypatch):
    class NS(spreadsheet.MockSheetCase):
        def backend(self):
            be = super().backend(); be.solve = lambda: False; return be
    monkeypatch.setattr(spreadsheet, "MockSheetCase", NS)
    r = call("write_to_hysys", name="h", confirm=True, method="spreadsheet")[1]
    assert r["solved"] is False and "propagation_ok" not in r


def test_spreadsheet_live_uses_sheet_case_with_names(loaded, tmp_path, monkeypatch):
    seen = {}
    class FakeSheet(spreadsheet.MockSheetCase):
        def __init__(self, lay, in_sheet, out_sheet, case_path, use_active, visible):
            super().__init__(lay); seen["args"] = (in_sheet, out_sheet, case_path, use_active, visible)
    monkeypatch.setattr(spreadsheet, "HysysSheetCase", FakeSheet)
    monkeypatch.setenv("HYSYS_LIVE", "1")
    case = tmp_path / "c.hsc"; case.write_bytes(b"")
    r = call("write_to_hysys", name="h", confirm=True, method="spreadsheet", live=True, case_path=str(case),
             in_sheet="IN1", out_sheet="OUT1", visible=True)[1]
    assert seen["args"] == ("IN1", "OUT1", str(case), False, True) and r["backend"] == "HYSYS" and "warning" not in r
    r = call("write_to_hysys", name="h", confirm=True, method="spreadsheet", live=True, use_active=True)[1]
    assert seen["args"] == ("HMB_IN", "HMB_OUT", None, True, False)


def test_spreadsheet_live_gates(loaded, monkeypatch):
    err, msg = call("write_to_hysys", name="h", confirm=True, method="spreadsheet", live=True, use_active=True)
    assert err and "requires HYSYS_LIVE=1" in msg
    monkeypatch.setenv("HYSYS_LIVE", "1")
    err, msg = call("write_to_hysys", name="h", confirm=True, method="spreadsheet", live=True)
    assert err and "live write needs case_path or use_active=true" in msg
    monkeypatch.setenv("HYSYS_LIVE", "true")
    assert "requires HYSYS_LIVE=1" in call("write_to_hysys", name="h", confirm=True, method="spreadsheet", live=True, use_active=True)[1]


def test_spreadsheet_layout_tool_sample_and_file(loaded, tmp_path):
    err, r = call("spreadsheet_layout", name="h")
    assert r["in_rows"] == 12 and r["out_rows"] == 4 * (6 + 2) and len(r["out_sample"]) == 12 and len(r["in"]) == 12
    assert r["contract"][-1] == "Row numbers below are 0-based Cell(col,row) indices." and "layout_csv" not in r
    p = tmp_path / "l.csv"
    assert call("spreadsheet_layout", name="h", path=str(p))[1]["layout_csv"] == str(p)
    assert p.read_text().startswith("sheet,row,label,unit,hysys_link")
    err, msg = call("spreadsheet_layout", name="h", path=str(p))
    assert err and "overwrite" in msg
    assert not call("spreadsheet_layout", name="h", path=str(p), overwrite=True)[0]


# ---- exports / extract --------------------------------------------------------------------------------------
def test_export_dexpi_process_splits_path(loaded, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(dexpi_process, "export_json", lambda fs, d, f: calls.append((fs, d, f)))
    p = tmp_path / "proc.json"
    err, r = call("export_dexpi_process", name="h", path=str(p))
    assert not err and r == {"wrote": str(p)} and calls == [(M.SESSIONS["h"], str(tmp_path), "proc.json")]
    p.write_text("x")
    assert "overwrite" in call("export_dexpi_process", name="h", path=str(p))[1]
    assert not call("export_dexpi_process", name="h", path=str(p), overwrite=True)[0]
    assert call("export_dexpi_process", name="h", path=str(tmp_path / "p.xml"))[0] is False   # .xml is a permitted export type
    assert call("export_dexpi_process", name="h", path=str(tmp_path / "p.exe"))[0] is True


def test_extract_pid_gates_and_runs(tmp_path, monkeypatch):
    img = tmp_path / "d.png"; img.write_bytes(b"x")
    r = call("extract_pid", name="p", path=str(img), confirm_upload=False)[1]
    assert r["extracted"] is False and "uploads the drawing" in r["reason"]
    err, msg = call("extract_pid", name="p", path=str(img), confirm_upload=True)
    assert err and msg == "PermissionError: ANTHROPIC_API_KEY is not set in the server environment"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    seen = {}
    def fake_extract(path, page=1, ask=None):
        seen["a"] = (path, page); fs = Flowsheet(); fs.units["U1"] = Unit(id="U1", type="pump"); return fs
    monkeypatch.setattr(pid_extract, "extract", fake_extract)
    err, r = call("extract_pid", name="p", path=str(img), confirm_upload=True, page=4)
    assert not err and seen["a"] == (str(img), 4) and r["units"] == {"U1": "pump"} and "DRAFT" in r["note"]
    call("extract_pid", name="p", path=str(img), confirm_upload=True)
    assert seen["a"][1] == 1                                          # default page
    bad = tmp_path / "d.gif"; bad.write_bytes(b"x")
    err, msg = call("extract_pid", name="p", path=str(bad), confirm_upload=True)
    assert err and "not allowed here" in msg


# ---- JSON-RPC layer ------------------------------------------------------------------------------------------
def test_initialize_defaults_protocol_version():
    r = rpc("initialize")["result"]
    assert r["protocolVersion"] == "2024-11-05" and r["serverInfo"] == {"name": "hysys-bridge", "version": "0.1.0"}


def test_ping_and_unknown_method_and_notification():
    assert rpc("ping") == {"jsonrpc": "2.0", "id": 1, "result": {}}
    r = rpc("whatever", mid=7)
    assert r["id"] == 7 and r["error"] == {"code": -32601, "message": "method not found: whatever"}
    assert rpc("ping", mid=None) is None
    assert rpc("ping", mid=0)["id"] == 0                              # id 0 is a request, not a notification


def test_tools_list_matches_registry():
    tools = rpc("tools/list")["result"]["tools"]
    assert [t["name"] for t in tools] == list(M.TOOLS)
    t = {x["name"]: x for x in tools}["write_to_hysys"]
    assert t["inputSchema"]["required"] == ["name"] and t["inputSchema"]["additionalProperties"] is False
    assert t["inputSchema"]["properties"]["method"]["enum"] == ["com", "spreadsheet"]


def test_unknown_tool_is_protocol_error():
    r = rpc("tools/call", {"name": "nope", "arguments": {}})
    assert r["error"] == {"code": -32602, "message": "unknown tool 'nope'"}


def test_argument_validation_messages():
    r = call("summarize")
    assert r == (True, "ValueError: missing ['name'] / unexpected []")
    assert call("summarize", name="x", bogus=1) == (True, "ValueError: missing [] / unexpected ['bogus']")
    r = rpc("tools/call", {"name": "status"})["result"]                      # arguments omitted entirely
    assert r["isError"] is False
    r = rpc("tools/call", {"name": "status", "arguments": None})["result"]
    assert r["isError"] is False
    assert call("load_hmb", name="x") == (True, "ValueError: pass path or csv_text")


def test_errors_do_not_leak_tracebacks(capsys, loaded):
    call("summarize", name="zzz")
    assert capsys.readouterr().err == ""


def test_debug_env_prints_traceback_to_stderr(capsys, monkeypatch):
    monkeypatch.setenv("HYSYS_BRIDGE_DEBUG", "1")
    err, msg = call("summarize", name="zzz")
    assert err and msg.startswith("KeyError")
    assert "Traceback" in capsys.readouterr().err


def test_non_string_results_are_json_with_default_str():
    text = rpc("tools/call", {"name": "status", "arguments": {}})["result"]["content"][0]["text"]
    assert text.startswith("{\n  \"version\"")                              # indent=2


# ---- stdio loop ---------------------------------------------------------------------------------------------
def run_main(monkeypatch, capsys, text):
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    M.main()
    return [json.loads(l) for l in capsys.readouterr().out.splitlines()]


def test_main_loop_replies_skips_blank_and_notifications(monkeypatch, capsys):
    text = "\n".join([json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}), "", "   ",
                      json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                      "not json", json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})]) + "\n"
    out = run_main(monkeypatch, capsys, text)
    assert out == [{"jsonrpc": "2.0", "id": 1, "result": {}},
                   {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}},
                   {"jsonrpc": "2.0", "id": 2, "result": {}}]


def test_main_guard(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 5, "method": "ping"}) + "\n"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        runpy.run_module("hysys_bridge.mcp_server", run_name="__main__")
    assert json.loads(capsys.readouterr().out) == {"jsonrpc": "2.0", "id": 5, "result": {}}
