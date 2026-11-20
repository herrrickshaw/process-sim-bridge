"""MCP tools for the casebook. The case directory and the DWSIM command are operator-set (CASEBOOK_DIR, DWSIM_MCP_CMD), never tool arguments;
the ledger is only written with confirm=true; no simulator case is saved."""
from __future__ import annotations
import glob, os, re
from . import schema, runner, ledger

DEFAULT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "studies", "cases")


def _dir(): return os.environ.get("CASEBOOK_DIR", DEFAULT_DIR)


def _load(case_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(case_id)): raise ValueError("case_id must be lowercase letters, digits and hyphens")
    path = os.path.join(_dir(), case_id + ".json")
    if not os.path.isfile(path): raise KeyError(f"no case {case_id!r} in the case directory (see casebook_list)")
    return schema.load(path)


def t_list(a):
    rows = []
    for p in sorted(glob.glob(os.path.join(_dir(), "*.json"))):
        c = schema.load(p); probs = schema.validate(c)
        rows.append({"id": c.get("id"), "status": c.get("status"), "valid": not probs, "problems": probs[:5], **(schema.capability(c) if not probs else {})})
    return {"cases": rows}


def t_validate(a):
    c = _load(a["case_id"]); probs = schema.validate(c)
    return {"case": a["case_id"], "valid": not probs, "problems": probs, "capability": schema.capability(c) if not probs else None, "hash": schema.case_hash(c)}


def t_run(a):
    c = _load(a["case_id"]); probs = schema.validate(c)
    if probs: return {"ran": False, "reason": "case is not valid", "problems": probs}
    run = runner.run_case(c, packages=a.get("packages"), scenarios=a.get("scenarios"))
    if run["ran"]:
        if a.get("confirm") is True: run["ledger_rows_written"] = ledger.append(runner.ledger_rows(run))
        else: run["ledger"] = "not written: pass confirm=true to append the results to studies/ledger.jsonl"
    return run


_s = lambda props, req=(): {"type": "object", "properties": props, "required": list(req)}
TOOLS = {
    "casebook_list": (t_list, "List the reference cases (from published studies) in the operator's case directory: status, validity, and whether every unit type is verified on the DWSIM backend.", _s({})),
    "casebook_validate": (t_validate, "Check one case record: every number has a source anchor or an assumed reason, pressure and composition bases are stated, reconstructed values say how they were checked.", _s({"case_id": {"type": "string"}}, ["case_id"])),
    "casebook_run": (t_run, "Run a case on DWSIM (needs DWSIM_MCP_CMD) for each listed property package and scenario and compare with the published values; reports error per package and the spread between packages. Nothing is tuned. confirm=true appends the rows to the ledger.",
                     _s({"case_id": {"type": "string"}, "packages": {"type": "array", "items": {"type": "string"}}, "scenarios": {"type": "array", "items": {"type": "string"}}, "confirm": {"type": "boolean"}}, ["case_id"])),
}
