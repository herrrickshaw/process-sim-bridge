"""MCP tools that drive Aspen Plus from the in-memory flowsheet sessions of hysys_bridge.mcp_server (registered into its TOOLS).

Same safety policy as the HYSYS and DWSIM tools:
  * Nothing reaches Aspen until aspen_build with confirm=true; validation errors or missing specs block it.
  * A MockTree is used unless live=true AND ASPEN_MODEL_PATH is set in the server's environment AND the host is Windows
    with Aspen Plus. The model path is operator-set; a tool argument can never supply it.
  * Never saves or overwrites a model file. aspen_run reports missing inputs by node path instead of guessing.
  * AspenComTree has never been run (no Aspen here), so live use is untested; the mock only checks the write plan.
"""
from __future__ import annotations
import os
from .. import validate as _validate, hysys_writer
from ..dwsim.guardrails import check_specs
from .backend import AspenBackend, MockTree, AspenComTree
from . import catalogue as C

CASES: dict[str, dict] = {}                 # session name -> {"be": AspenBackend, "tree": Tree, "live": bool}


def _fs(name):
    from .. import mcp_server as M          # late import: mcp_server imports this module
    return M._fs(name)


def _case(name):
    if name not in CASES: raise KeyError(f"no Aspen case for session {name!r}; run aspen_build first (built: {sorted(CASES) or 'none'})")
    return CASES[name]


def _close(name):
    c = CASES.pop(name, None)
    if c and hasattr(c["tree"], "close"): c["tree"].close()


def t_status(a):
    p = os.environ.get("ASPEN_MODEL_PATH")
    return {"live_possible": bool(p), "ASPEN_MODEL_PATH_set": bool(p), "built_cases": sorted(CASES),
            "unverified_unit_types": sorted(C.UNVERIFIED_UNITS),
            "note": "AspenComTree has never run against a real Aspen Plus; the mock checks the write plan only"}


def t_check_specs(a):
    miss = check_specs(_fs(a["name"]))
    return {"complete": not miss, "missing": miss}


def t_build(a):
    fs = _fs(a["name"])
    iss = _validate.blocking(_validate.validate(fs)); miss = check_specs(fs)
    if iss or miss:
        return {"built": False, "reason": "validation errors or missing specs block the build", "errors": [str(i) for i in iss], "missing": miss}
    if not a.get("confirm"):
        return {"built": False, "reason": "dry plan only: pass confirm=true to build", "specs": len(hysys_writer.plan_specs(fs))}
    live = bool(a.get("live"))
    if live and not os.environ.get("ASPEN_MODEL_PATH"): raise PermissionError("live=true requires ASPEN_MODEL_PATH in the server environment")
    _close(a["name"])
    tree = AspenComTree(os.environ["ASPEN_MODEL_PATH"]) if live else MockTree()
    be = AspenBackend(tree, allow_unverified=bool(a.get("allow_unverified")))
    try:
        rows = hysys_writer.write(fs, be)
    except NotImplementedError as e:
        if hasattr(tree, "close"): tree.close()
        return {"built": False, "reason": str(e)}
    except Exception:
        if hasattr(tree, "close"): tree.close()
        raise
    CASES[a["name"]] = {"be": be, "tree": tree, "live": live}
    bad = [str(r) for r in rows if r.status != "OK"]
    return {"built": True, "backend": "Aspen" if live else "mock", "specs_written": len(rows), "not_ok": bad, "saved": False}


def t_run(a):
    c = _case(a["name"]); be = c["be"]
    ok = be.solve(float(a.get("timeout_s", 300)))
    return {"solved": ok, "backend": "Aspen" if c["live"] else "mock", "finished": be.last_run["finished"],
            "missing_inputs": be.last_run["missing_inputs"], "block_status": be.last_run["blocks"]}


def t_read_stream(a):
    c = _case(a["name"])
    if not c["be"].last_run.get("ok"): raise RuntimeError("run first: results exist only after a successful aspen_run")
    return {"stream": a["stream"], "backend": "Aspen" if c["live"] else "mock",
            **{p: c["be"].read_result(a["stream"], p) for p in ("T", "P")}}


def t_close(a):
    _case(a["name"]); _close(a["name"]); return {"closed": a["name"]}


def _s(props, req): return {"type": "object", "properties": props, "required": req, "additionalProperties": False}
_n = {"type": "string", "description": "session name"}
_b = {"type": "boolean"}

TOOLS = {
    "aspen_status": (t_status, "Whether a live Aspen model is configured (ASPEN_MODEL_PATH), which cases are built, which unit types are unverified.", _s({}, [])),
    "aspen_check_specs": (t_check_specs, "List required inputs still missing in a session. No side effects.", _s({"name": _n}, ["name"])),
    "aspen_build": (t_build, "Write a validated session into Aspen (mock tree unless live=true and ASPEN_MODEL_PATH is set). Needs confirm=true. valve/compressor are refused unless allow_unverified=true. Never saves a model.",
                    _s({"name": _n, "confirm": _b, "live": _b, "allow_unverified": _b}, ["name"])),
    "aspen_run": (t_run, "Reinit and run the Aspen engine; reports unfinished runs, missing inputs by node path, and block status.", _s({"name": _n, "timeout_s": {"type": "number"}}, ["name"])),
    "aspen_read_stream": (t_read_stream, "Result T and P of one stream after a successful run (other properties are not documented in the source repos).", _s({"name": _n, "stream": {"type": "string"}}, ["name", "stream"])),
    "aspen_close": (t_close, "Close the Aspen case and release the COM thread.", _s({"name": _n}, ["name"])),
}
