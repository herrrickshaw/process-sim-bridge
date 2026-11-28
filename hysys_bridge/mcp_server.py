"""MCP server (stdio, JSON-RPC 2.0, standard library only) linking H&MB tables, P&ID/DEXPI and Aspen HYSYS.

Run:   python3 -m hysys_bridge.mcp_server          (add to .mcp.json / claude_desktop_config.json)

Design (patterned on brack101/AspenPlus-MCP-Server, MIT: stdio MCP server + COM wrapper, Windows-only, degrades
gracefully elsewhere) but with writes gated:
  * Everything works on in-memory *sessions* (named flowsheets). Nothing touches HYSYS until write_to_hysys.
  * Every true/false argument must be a JSON boolean; text such as "false", numbers and null are refused.
  * write_to_hysys needs confirm=true AND blocks on validation errors. It uses the MOCK backend unless live=true,
    HYSYS_LIVE=1 is set in the server's environment, and the platform is Windows with HYSYS installed.
  * A live write goes only into a case the caller names (case_path, or use_active=true). It never saves or
    overwrites a case file; saving is left to the user inside HYSYS.
  * extract_pid uploads the drawing to Anthropic's API, so it needs confirm_upload=true and ANTHROPIC_API_KEY.
  * File reads are limited to .csv/.json/.xml/.pdf/.png/.jpg; exports refuse to overwrite unless overwrite=true.
"""
from __future__ import annotations
import csv, dataclasses, io, json, os, sys, traceback
from . import extract_hmb, normalize as _normalize, validate as _validate, hysys_writer, hmb_check
from . import pid_reconcile, pid_eval, pid_extract, dexpi_export, spreadsheet
from .ir import Flowsheet
from .backend import MockHysys

VERSION = "0.1.0"
SESSIONS: dict[str, Flowsheet] = {}
READ_OK = {".csv", ".json", ".xml", ".pdf", ".png", ".jpg", ".jpeg"}
WRITE_OK = {".xml", ".json", ".csv"}


def _read_path(path: str, allowed=READ_OK) -> str:
    p = os.path.abspath(os.path.expanduser(path)); ext = os.path.splitext(p)[1].lower()
    if ext not in allowed: raise ValueError(f"file type {ext or '(none)'} not allowed here; allowed: {sorted(allowed)}")
    if not os.path.isfile(p): raise FileNotFoundError(p)
    return p


def _write_path(path: str, overwrite: bool) -> str:
    p = os.path.abspath(os.path.expanduser(path)); ext = os.path.splitext(p)[1].lower()
    if ext not in WRITE_OK: raise ValueError(f"export type {ext or '(none)'} not allowed; allowed: {sorted(WRITE_OK)}")
    if os.path.exists(p) and not overwrite: raise FileExistsError(f"{p} exists; pass overwrite=true to replace it")
    return p


def _fs(name: str) -> Flowsheet:
    if name not in SESSIONS: raise KeyError(f"no session {name!r}; loaded: {sorted(SESSIONS) or 'none'}")
    return SESSIONS[name]


def _summary(name: str) -> dict:
    fs = _fs(name)
    return {"session": name, "units": {u.id: u.type for u in fs.units.values()},
            "streams": {s.id: f"{s.src or 'FEED'} -> {s.dst or 'PRODUCT'}" for s in fs.streams.values()},
            "components": fs.components, "fluid_package": fs.fluid_package}


def _issues(items): return [str(i) for i in items]


# ---- tools ------------------------------------------------------------------------------------------------
def t_status(a):
    live_ok = sys.platform == "win32" and os.environ.get("HYSYS_LIVE") == "1"
    try:
        import win32com.client  # noqa: F401
        com = True
    except ImportError:
        com = False
    return {"version": VERSION, "platform": sys.platform, "pywin32": com, "HYSYS_LIVE": os.environ.get("HYSYS_LIVE") == "1",
            "live_writes_possible": bool(live_ok and com), "sessions": sorted(SESSIONS),
            "note": "Live HYSYS writes are untested on this build; use the mock backend to rehearse."}


def t_load_hmb(a):
    if "csv_text" in a:
        fs = extract_hmb.from_rows(list(csv.reader(io.StringIO(a["csv_text"]))), origin="inline")
    else:
        p = _read_path(a["path"], {".csv", ".pdf"})
        fs = extract_hmb.from_pdf(p, a.get("page")) if p.lower().endswith(".pdf") else extract_hmb.from_csv(p)
    fs.fluid_package = a.get("fluid_package", fs.fluid_package); SESSIONS[a["name"]] = fs
    return _summary(a["name"])


def t_load_dexpi(a):
    SESSIONS[a["name"]] = dexpi_export.load(_read_path(a["path"], {".xml"})); return _summary(a["name"])


def t_load_flowsheet_json(a):
    SESSIONS[a["name"]] = Flowsheet.from_json(_read_path(a["path"], {".json"})); return _summary(a["name"])


def t_summarize(a): return _summary(a["name"])


def t_normalize(a): return {"actions": _normalize.normalize(_fs(a["name"])), **_summary(a["name"])}


def t_validate(a):
    iss = _validate.validate(_fs(a["name"]))
    return {"errors": _issues(i for i in iss if i.level == "error"), "warnings": _issues(i for i in iss if i.level == "warn"),
            "blocks_hysys_write": bool(_validate.blocking(iss))}


def t_reconcile(a):
    iss, acts = pid_reconcile.reconcile(_fs(a["name"]), fix=bool(a.get("fix", False)))
    return {"auto_fixes_applied": acts, "findings": _issues(iss)}


def t_merge_pid_hmb(a):
    notes = pid_extract.merge_values(_fs(a["topology"]), _fs(a["hmb"]))
    return {"conflicts_and_gaps": notes, **_summary(a["topology"])}


def t_score(a):
    return {"score": str(pid_eval.score(_fs(a["name"]), _fs(a["truth"]), a.get("mode", "id"))),
            "caveat": "P/R/F1 on a graph without geometry; not comparable to the PID2Graph edge mAP"}


def t_plan_specs(a):
    plan = hysys_writer.plan_specs(_fs(a["name"]))
    return {"count": len(plan), "specs": [{"stream": s, "prop": p, "value": v} for s, p, v in plan],
            "policy": "only independent specs are written; H&MB enthalpy/VF/downstream values are compared after solve"}


def t_write_to_hysys(a):
    fs = _fs(a["name"])
    iss = _validate.validate(fs)
    if _validate.blocking(iss):
        return {"written": False, "reason": "validation errors block the write", "errors": _issues(_validate.blocking(iss))}
    if not a.get("confirm"):
        return {"written": False, "reason": "dry plan only: pass confirm=true to write", "specs": len(hysys_writer.plan_specs(fs))}
    live = bool(a.get("live"))
    if a.get("method", "com") == "spreadsheet":
        return _write_spreadsheet(fs, a, live)
    if live:
        if os.environ.get("HYSYS_LIVE") != "1": raise PermissionError("live=true requires HYSYS_LIVE=1 in the server environment")
        if not (a.get("case_path") or a.get("use_active")): raise PermissionError("live write needs case_path or use_active=true")
        from .backend import HysysCOM
        cp = _read_path(a["case_path"], {".hsc"}) if a.get("case_path") else None
        be = HysysCOM(visible=bool(a.get("visible", False)), open_path=cp, use_active=bool(a.get("use_active")))
    else:
        be = MockHysys()
    audit = _write_path(a["audit_csv"], bool(a.get("overwrite"))) if a.get("audit_csv") else None
    rows = hysys_writer.write(fs, be, audit)
    bad = [dataclasses.asdict(r) for r in rows if r.status != "OK"]
    out = {"written": True, "backend": "HYSYS" if live else "mock", "values_written": len(rows), "readback_mismatches": bad[:50],
           "audit_csv": audit, "saved": False}
    if bad: out["next"] = "fix mismatches before solving"; return out
    solved = be.solve()
    out["solved"] = solved
    if solved:
        diffs = [dataclasses.asdict(d) for d in hmb_check.check(fs, be) if not d.ok]
        out["hmb_disagreements"] = diffs[:100]; out["hmb_disagreement_count"] = len(diffs)
        if not live: out["warning"] = "mock backend performs no calculation: disagreements are expected"
    return out


def t_spreadsheet_layout(a):
    lay = spreadsheet.build_layout(_fs(a["name"]), a.get("units"))
    out = {"units": lay.units, "in_rows": len(lay.inputs), "out_rows": len(lay.outputs),
           "contract": ["Build spreadsheet operations HMB_IN and HMB_OUT in the HYSYS case (names are arguments of write_to_hysys).",
                        "Column 0 = label, column 1 = value. IN column 1 cells are EXPORTED to the listed stream variables; OUT cells IMPORT them.",
                        "Set the listed unit on every linked variable. Pressures are ABSOLUTE.",
                        "Row numbers below are 0-based Cell(col,row) indices."],
           "in": [{"row": i.row, "label": i.key, "unit": i.unit} for i in lay.inputs],
           "out_sample": [{"row": i.row, "label": i.key, "unit": i.unit} for i in lay.outputs[:12]]}
    if a.get("path"):
        p = _write_path(a["path"], bool(a.get("overwrite")))
        with open(p, "w", encoding="utf-8", newline="") as f: f.write(lay.csv())
        out["layout_csv"] = p
    return out


def _write_spreadsheet(fs, a, live):
    lay = spreadsheet.build_layout(fs, a.get("units"))
    if live:
        if os.environ.get("HYSYS_LIVE") != "1": raise PermissionError("live=true requires HYSYS_LIVE=1 in the server environment")
        if not (a.get("case_path") or a.get("use_active")): raise PermissionError("live write needs case_path or use_active=true")
        cp = _read_path(a["case_path"], {".hsc"}) if a.get("case_path") else None
        case = spreadsheet.HysysSheetCase(lay, a.get("in_sheet", "HMB_IN"), a.get("out_sheet", "HMB_OUT"), cp,
                                          bool(a.get("use_active")), bool(a.get("visible", False)))
    else:
        case = spreadsheet.MockSheetCase(lay)
    be = case.backend()
    audit = _write_path(a["audit_csv"], bool(a.get("overwrite"))) if a.get("audit_csv") else None
    rows = hysys_writer.write(fs, be, audit)
    bad = [dataclasses.asdict(r) for r in rows if r.status != "OK"]
    out = {"written": True, "method": "spreadsheet", "backend": "HYSYS" if live else "mock", "units": lay.units,
           "cells_written": len(lay.inputs), "readback_mismatches": bad[:50], "saved": False}
    if bad: out["next"] = "fix mismatches before solving"; return out
    out["solved"] = solved = be.solve()
    if solved:
        prop = [p for p in spreadsheet.verify_propagation(fs, be) if not p.ok]
        out["propagation_failures"] = [str(p) for p in prop[:100]]
        out["propagation_ok"] = not prop
        if prop: out["hint"] = "unlinked cell, wrong variable or wrong unit set on the OUT/IN sheet: fix the HYSYS links, do not trust the case"
        diffs = [dataclasses.asdict(d) for d in hmb_check.check(fs, be) if not d.ok]
        out["hmb_disagreements"] = diffs[:100]; out["hmb_disagreement_count"] = len(diffs)
        if not live: out["warning"] = "mock case imitates the links (IN copied to OUT): it proves the plumbing, not HYSYS"
    return out


def t_export_dexpi(a):
    p = _write_path(a["path"], bool(a.get("overwrite"))); dexpi_export.export(_fs(a["name"]), p); return {"wrote": p}


def t_export_dexpi_process(a):
    from . import dexpi_process
    p = _write_path(a["path"], bool(a.get("overwrite"))); d, f = os.path.split(p)
    dexpi_process.export_json(_fs(a["name"]), d, f); return {"wrote": p}


def t_extract_pid(a):
    if not a.get("confirm_upload"):
        return {"extracted": False, "reason": "this uploads the drawing to Anthropic's API; pass confirm_upload=true to proceed"}
    if not os.environ.get("ANTHROPIC_API_KEY"): raise PermissionError("ANTHROPIC_API_KEY is not set in the server environment")
    p = _read_path(a["path"], {".png", ".jpg", ".jpeg", ".pdf"})
    SESSIONS[a["name"]] = pid_extract.extract(p, int(a.get("page", 1)))
    return {"note": "topology DRAFT (units flagged needs-signoff); run reconcile, merge_pid_hmb and review before writing", **_summary(a["name"])}


def _s(props: dict, req: list[str]): return {"type": "object", "properties": props, "required": req, "additionalProperties": False}
_n = {"type": "string", "description": "session name"}
_p = {"type": "string"}
_b = {"type": "boolean"}

TOOLS = {
    "status": (t_status, "Platform, pywin32/HYSYS availability, whether live writes are enabled, loaded sessions.", _s({}, [])),
    "load_hmb": (t_load_hmb, "Load a Heat & Mass Balance table (CSV, vector PDF, or inline csv_text) into a session.",
                 _s({"name": _n, "path": _p, "csv_text": _p, "page": {"type": "integer"}, "fluid_package": _p}, ["name"])),
    "load_dexpi": (t_load_dexpi, "Load a P&ID exported by this tool (DEXPI-style Proteus XML) into a session.", _s({"name": _n, "path": _p}, ["name", "path"])),
    "load_flowsheet_json": (t_load_flowsheet_json, "Load a saved flowsheet IR JSON.", _s({"name": _n, "path": _p}, ["name", "path"])),
    "extract_pid": (t_extract_pid, "Vision-LLM topology draft from a P&ID image/PDF (uploads the file; needs confirm_upload=true and ANTHROPIC_API_KEY).",
                    _s({"name": _n, "path": _p, "page": {"type": "integer"}, "confirm_upload": _b}, ["name", "path"])),
    "summarize": (t_summarize, "Units, streams and components in a session.", _s({"name": _n}, ["name"])),
    "normalize": (t_normalize, "Insert implicit mixers/splitters (rule-based).", _s({"name": _n}, ["name"])),
    "validate": (t_validate, "Units, bounds, composition sums, mass balance. Errors block the HYSYS write.", _s({"name": _n}, ["name"])),
    "reconcile": (t_reconcile, "Domain-rule checks on topology; fix=true applies only self-loop/isolated-unit removals.",
                  _s({"name": _n, "fix": _b}, ["name"])),
    "merge_pid_hmb": (t_merge_pid_hmb, "Copy numbers from an H&MB session onto a P&ID topology session; reports conflicts.",
                      _s({"topology": _n, "hmb": _n}, ["topology", "hmb"])),
    "score": (t_score, "Score a session against a ground-truth session (node/edge P/R/F1, adjacency).",
              _s({"name": _n, "truth": _n, "mode": {"type": "string", "enum": ["id", "structure"]}}, ["name", "truth"])),
    "plan_specs": (t_plan_specs, "List the independent specs that would be written to HYSYS (no side effects).", _s({"name": _n}, ["name"])),
    "write_to_hysys": (t_write_to_hysys, "Write validated specs, read every value back, solve, compare with the H&MB. Needs confirm=true; mock backend unless live=true + HYSYS_LIVE=1 + case_path/use_active. method=spreadsheet uses the HMB_IN/HMB_OUT spreadsheet contract (see spreadsheet_layout). Never saves the case.",
                       _s({"name": _n, "confirm": _b, "live": _b, "case_path": _p, "use_active": _b, "visible": _b, "audit_csv": _p, "overwrite": _b,
                         "method": {"type": "string", "enum": ["com", "spreadsheet"]}, "in_sheet": _p, "out_sheet": _p, "units": {"type": "object"}}, ["name"])),
    "spreadsheet_layout": (t_spreadsheet_layout, "Row contract for the HYSYS spreadsheet link (IN/OUT sheets, units); optional CSV file. Build these sheets in HYSYS once.",
                           _s({"name": _n, "units": {"type": "object"}, "path": _p, "overwrite": _b}, ["name"])),
    "export_dexpi": (t_export_dexpi, "Write the P&ID as DEXPI-style Proteus XML.", _s({"name": _n, "path": _p, "overwrite": _b}, ["name", "path"])),
    "export_dexpi_process": (t_export_dexpi_process, "Write the DEXPI Process model JSON (needs pydexpi).", _s({"name": _n, "path": _p, "overwrite": _b}, ["name", "path"])),
}
from .dwsim.tools import TOOLS as _DWSIM_TOOLS        # dwsim_* tools drive DWSIM from the same sessions
TOOLS.update(_DWSIM_TOOLS)
from .aspen.tools import TOOLS as _ASPEN_TOOLS        # aspen_* tools (mock tree by default; live COM untested)
TOOLS.update(_ASPEN_TOOLS)
from .safety_link import TOOLS as _SAFETY_TOOLS      # safety_* tools: solved streams -> process-safety-design-toolkit
TOOLS.update(_SAFETY_TOOLS)
from .refinery_link import TOOLS as _REFINERY_TOOLS   # refinery_* tools: whole-refinery screening balance
TOOLS.update(_REFINERY_TOOLS)
from .steam_link import TOOLS as _STEAM_TOOLS         # steam_* tools: heat duty -> steam demand vs the NETL B11A cycle
TOOLS.update(_STEAM_TOOLS)
from .utilities_link import TOOLS as _UTIL_TOOLS      # utility_* tools: air, nitrogen, cooling water, demin water, plant balance
TOOLS.update(_UTIL_TOOLS)
from .polymer_link import TOOLS as _POLYMER_TOOLS     # polymer_* tools: method-of-moments stream attributes and mixing (Aspen Polymers arithmetic)
TOOLS.update(_POLYMER_TOOLS)
from .hmb_report_link import TOOLS as _HMB_REPORT_TOOLS  # safety_hmb_report: HMB closure / model / P&ID audit via the safety toolkit
TOOLS.update(_HMB_REPORT_TOOLS)

from .casebook.tools import TOOLS as _CASEBOOK_TOOLS  # casebook_* tools: published reference cases run on DWSIM and compared
TOOLS.update(_CASEBOOK_TOOLS)
from .datasheet_check import TOOLS as _DATASHEET_TOOLS  # datasheet_check: attribute mismatches across P&ID, H&MB and vendor data sheets
TOOLS.update(_DATASHEET_TOOLS)
from .lng_link import TOOLS as _LNG_TOOLS  # lng_cost_*: LNG value-chain cost estimate (lng-cost repo), capacity from a solved stream
TOOLS.update(_LNG_TOOLS)
from .ppac_link import TOOLS as _PPAC_TOOLS  # ppac_*: PPAC Ready Reckoner tables as reference data (ppac-ready-reckoner-data repo)
TOOLS.update(_PPAC_TOOLS)


# ---- JSON-RPC / MCP stdio loop ----------------------------------------------------------------------------
def handle(msg: dict):
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None: return None                                        # notification
    def ok(result): return {"jsonrpc": "2.0", "id": mid, "result": result}
    def err(code, text): return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}
    if method == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}},
                   "serverInfo": {"name": "hysys-bridge", "version": VERSION}})
    if method == "ping": return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": n, "description": d, "inputSchema": sch} for n, (_, d, sch) in TOOLS.items()]})
    if method == "tools/call":
        name = params.get("name")
        if name not in TOOLS: return err(-32602, f"unknown tool {name!r}")
        fn, _, schema = TOOLS[name]; args = params.get("arguments") or {}
        missing = [k for k in schema["required"] if k not in args]
        extra = [k for k in args if k not in schema["properties"]]
        # Handlers test flags by truthiness, where the text "false" would count as yes: accept real booleans only.
        not_bool = [k for k, v in args.items() if schema["properties"].get(k, {}).get("type") == "boolean" and not isinstance(v, bool)]
        try:
            if missing or extra: raise ValueError(f"missing {missing} / unexpected {extra}")
            if not_bool: raise ValueError(f"{not_bool} must be true or false (a JSON boolean, not text, a number or null)")
            if name == "load_hmb" and not ({"path", "csv_text"} & set(args)): raise ValueError("pass path or csv_text")
            res = fn(args); is_err = False
        except SystemExit as e:
            res, is_err = f"{e}", True
        except Exception as e:                                          # message only: no tracebacks/paths leak into the chat
            res, is_err = f"{type(e).__name__}: {e}", True
            if os.environ.get("HYSYS_BRIDGE_DEBUG"): traceback.print_exc(file=sys.stderr)
        text = res if isinstance(res, str) else json.dumps(res, indent=2, default=str)
        return ok({"content": [{"type": "text", "text": text}], "isError": is_err})
    return err(-32601, f"method not found: {method}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        try:
            reply = handle(json.loads(line))
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n"); sys.stdout.flush()


if __name__ == "__main__":
    # Tool modules reach sessions through `from . import mcp_server`. Run that module: under -m, this file is a second copy
    # called "__main__" with its own empty SESSIONS.
    from hysys_bridge.mcp_server import main as _main
    _main()
