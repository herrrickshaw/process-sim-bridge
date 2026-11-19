"""MCP tools that drive DWSIM from the in-memory flowsheet sessions of hysys_bridge.mcp_server (registered into its TOOLS).

Same safety policy as the HYSYS tools:
  * Nothing reaches DWSIM until dwsim_build with confirm=true, and validation errors or missing specs block it.
  * The mock server (FakeDwsim) is used unless live=true AND DWSIM_MCP_CMD is set in the server's environment, e.g.
      DWSIM_MCP_CMD="podman run -i --rm --network none ghcr.io/danwbr/dwsim-mcp:latest --stdio"
    (verified 2026-11-20; see backend.py). The command is operator-set; a tool argument can never supply it.
  * Never saves a DWSIM case file. dwsim_solve refuses while the server reports open degrees of freedom.
"""
from __future__ import annotations
import os, shlex
from .. import validate as _validate, hysys_writer
from .backend import DwsimBackend, StdioTransport
from .fake import FakeDwsim
from .guardrails import check_specs

CASES: dict[str, dict] = {}                 # session name -> {"be": DwsimBackend, "transport": closable|None, "live": bool}


def _fs(name):
    from .. import mcp_server as M          # late import: mcp_server imports this module
    return M._fs(name)


def _case(name):
    if name not in CASES: raise KeyError(f"no DWSIM case for session {name!r}; run dwsim_build first (built: {sorted(CASES) or 'none'})")
    return CASES[name]


def _close(name):
    c = CASES.pop(name, None)
    if c and c["transport"] is not None: c["transport"].close()


def t_status(a):
    cmd = os.environ.get("DWSIM_MCP_CMD")
    return {"live_possible": bool(cmd), "DWSIM_MCP_CMD_set": bool(cmd), "built_cases": sorted(CASES),
            "note": "verified on pump/heater/cooler only; valve, compressor, splitter, vessel unit parameters are unverified"}


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
    if live and not os.environ.get("DWSIM_MCP_CMD"): raise PermissionError("live=true requires DWSIM_MCP_CMD in the server environment")
    _close(a["name"])
    transport = StdioTransport(shlex.split(os.environ["DWSIM_MCP_CMD"])) if live else None
    be = DwsimBackend(transport or FakeDwsim(), mw=a.get("molar_masses"))
    try:
        rows = hysys_writer.write(fs, be)
    except Exception:
        if transport: transport.close()
        raise
    CASES[a["name"]] = {"be": be, "transport": transport, "live": live}
    return {"built": True, "backend": "DWSIM" if live else "mock", "specs_buffered": len(rows), "saved": False,
            "note": "specs are buffered locally; they reach DWSIM at dwsim_solve. Pre-solve read-back is local, not from DWSIM."
                    + ("" if live else " Mock backend: nothing is calculated.")}


def t_solve(a):
    c = _case(a["name"]); be = c["be"]
    ok = be.solve()
    out = {"solved": ok, "backend": "DWSIM" if c["live"] else "mock"}
    if not ok:
        out.update({k: be.last_solve.get(k) for k in ("blocked", "open", "errors") if be.last_solve.get(k)})
        return out
    out["objects"] = [{"name": o["name"], "calculated": o.get("calculated"), "error": o.get("error", "")} for o in be.last_solve.get("objects", [])]
    out["mismatches_vs_specs"] = be.check_solution() if c["live"] else "skipped: mock backend calculates nothing"
    return out


def t_read_stream(a):
    c = _case(a["name"])
    if not c["be"].last_solve.get("ok"): raise RuntimeError("solve first: results exist only after a successful dwsim_solve")
    return {"stream": a["stream"], "units": {"T": "C", "P": "kPa", "mass": "kg/h", "mol_s": "mol/s"}, **c["be"].read_stream(a["stream"]),
            "backend": "DWSIM" if c["live"] else "mock"}


def t_close(a):
    _case(a["name"]); _close(a["name"]); return {"closed": a["name"]}


def _s(props, req): return {"type": "object", "properties": props, "required": req, "additionalProperties": False}
_n = {"type": "string", "description": "session name"}
_b = {"type": "boolean"}

TOOLS = {
    "dwsim_status": (t_status, "Whether a live DWSIM MCP server is configured (DWSIM_MCP_CMD) and which cases are built.", _s({}, [])),
    "dwsim_check_specs": (t_check_specs, "List required inputs still missing in a session (feed T/P/flow/composition, pump/valve outlet P, heater/cooler outlet T, connections). No side effects.",
                          _s({"name": _n}, ["name"])),
    "dwsim_build": (t_build, "Build a validated session as a DWSIM flowsheet. Needs confirm=true; mock server unless live=true and DWSIM_MCP_CMD is set. Blocks on validation errors or missing specs. Mole-basis compositions need molar_masses (g/mol) because DWSIM takes mass fractions. Never saves a case.",
                    _s({"name": _n, "confirm": _b, "live": _b, "molar_masses": {"type": "object"}}, ["name"])),
    "dwsim_solve": (t_solve, "Send buffered specs to DWSIM, refuse while degrees of freedom are open, solve, and compare DWSIM's results with the specs.", _s({"name": _n}, ["name"])),
    "dwsim_read_stream": (t_read_stream, "Real results of one stream after a solve: T (C), P (kPa), mass flow (kg/h), mass fractions.", _s({"name": _n, "stream": {"type": "string"}}, ["name", "stream"])),
    "dwsim_close": (t_close, "Close the DWSIM case and its server process.", _s({"name": _n}, ["name"])),
}
