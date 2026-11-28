"""MCP tools for the casebook. The case directory and the DWSIM command are operator-set (CASEBOOK_DIR, DWSIM_MCP_CMD), never tool arguments;
casebook_run and casebook_hazop have no mock, so they start DWSIM only with live=true; the ledger is only written with confirm=true; no simulator case is saved."""
from __future__ import annotations
import glob, os, re
import copy, json
from . import schema, runner, ledger, hazop, hazop_rules, hazop_nodes

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


def _not_live(a):
    """None if the caller asked for a live run, else the answer to give instead of starting DWSIM."""
    if a.get("live") is True: return None
    return {"ran": False, "reason": "this has no mock: it starts live DWSIM with the command in DWSIM_MCP_CMD. Pass live=true to run it."}


def _once(items):
    """Each package or scenario once, in order: a repeat would start another simulator run for nothing."""
    return list(dict.fromkeys(items)) if items else items


def t_run(a):
    c = _load(a["case_id"]); probs = schema.validate(c)
    if probs: return {"ran": False, "reason": "case is not valid", "problems": probs}
    stop = _not_live(a)
    if stop: return stop
    run = runner.run_case(c, packages=_once(a.get("packages")), scenarios=_once(a.get("scenarios")))
    if run["ran"]:
        if a.get("confirm") is True: run["ledger_rows_written"] = ledger.append(runner.ledger_rows(run))
        else: run["ledger"] = "not written: pass confirm=true to append the results to studies/ledger.jsonl"
    return run


HAZOP_DEFAULT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "studies", "hazop")


def _hazop_dir(): return os.environ.get("HAZOP_DIR", HAZOP_DEFAULT_DIR)


def load_spec(spec_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(spec_id)): raise ValueError("spec_id must be lowercase letters, digits and hyphens")
    path = os.path.join(_hazop_dir(), spec_id + ".json")
    if not os.path.isfile(path): raise KeyError(f"no HAZOP study {spec_id!r} in the study directory")
    with open(path) as f: return json.load(f)


def t_hazop(a):
    spec = load_spec(a["spec_id"]); case = _load(spec["case"]); probs = schema.validate(case)
    if probs: return {"ran": False, "reason": "case is not valid", "problems": probs}
    if a.get("packages"): spec = {**spec, "packages": _once(a["packages"])}
    sp = hazop.validate_spec(spec, case)
    if sp: return {"ran": False, "reason": "the study spec is not valid", "problems": sp}
    stop = _not_live(a)
    if stop: return stop
    ws = hazop.run_study(spec, case); return {"ran": True, "worksheet": ws, "markdown": hazop.render_markdown(ws)}


def t_hazop_rules(a):
    st = hazop_rules.load(); probs = hazop_rules.validate(st)
    if probs: return {"valid": False, "problems": probs}
    if "parameter" not in a: return {"valid": True, "sources": st["sources"], "counts": {k: len(st[k]) for k in ("causes", "safeguard_types", "worked_examples", "method_notes")}, "method_notes": st["method_notes"]}
    if a.get("guide_word") not in hazop_rules.GUIDE_WORDS: raise ValueError(f"guide_word must be one of {sorted(hazop_rules.GUIDE_WORDS)}")
    return {"valid": True, "suggestions": hazop_rules.suggest(st, a["parameter"], a["guide_word"], a.get("upstream_equipment")), "sources": st["sources"], "status": "candidates for the study team, none reviewed"}


def t_hazop_nodes(a):
    """Draft HAZOP nodes from a casebook case's topology, or from a loaded flowsheet session (a P&ID extraction) with the casebook case that supplies the values. Returns the draft spec; writes nothing."""
    sizes, sid, issues, case = a.get("sizes"), a.get("study_id", "draft-study"), None, (_load(a["case_id"]) if a.get("case_id") else None)
    if "session" in a:
        from .. import mcp_server, pid_reconcile
        fs = mcp_server._fs(a["session"]); issues = [str(i) for i in pid_reconcile.reconcile(copy.deepcopy(fs), fix=False)[0]]; g = hazop_nodes.graph_from_flowsheet(fs)
    else:
        if case is None: raise ValueError("pass case_id (a casebook case) or session (a loaded flowsheet)")
        g = hazop_nodes.graph_from_case(case)
    spec = hazop_nodes.derive(g, case, sid, sizes, issues)
    return {"spec": spec, "complete": spec["derivation"]["complete"], "next": "supply sizes with their reason, fix any mismatches, then save the spec in the study directory and run casebook_hazop"}


_s = lambda props, req=(): {"type": "object", "properties": props, "required": list(req)}
TOOLS = {
    "casebook_list": (t_list, "List the reference cases (from published studies) in the operator's case directory: status, validity, and whether every unit type is verified on the DWSIM backend.", _s({})),
    "casebook_validate": (t_validate, "Check one case record: every number has a source anchor or an assumed reason, pressure and composition bases are stated, reconstructed values say how they were checked.", _s({"case_id": {"type": "string"}}, ["case_id"])),
    "casebook_run": (t_run, "Run a case on live DWSIM (needs live=true and DWSIM_MCP_CMD; there is no mock) for each listed property package and scenario and compare with the published values; reports error per package and the spread between packages. Nothing is tuned. confirm=true appends the rows to the ledger.",
                     _s({"case_id": {"type": "string"}, "packages": {"type": "array", "items": {"type": "string"}}, "scenarios": {"type": "array", "items": {"type": "string"}}, "live": {"type": "boolean"}, "confirm": {"type": "boolean"}}, ["case_id"])),
    "casebook_hazop": (t_hazop, "Run a HAZOP deviation study (a spec in the operator's study directory) on its casebook case: each guide word plus parameter plus size is applied to a feed stream, solved on live DWSIM (needs live=true and DWSIM_MCP_CMD; there is no mock), and the consequences are read from the simulation and the guardrails (declared safe limits, material balance). Returns a worksheet; causes and safeguards are the team's, no severity or recommendation is assigned, steady-state only. Nothing is written.",
                       _s({"spec_id": {"type": "string"}, "packages": {"type": "array", "items": {"type": "string"}}, "live": {"type": "boolean"}}, ["spec_id"])),
    "casebook_hazop_rules": (t_hazop_rules, "Look up the HAZOP cause and safeguard rules store: candidate causes for a guide word and parameter (optionally limited to the equipment you say is upstream), safeguard types, worked examples from the cited sources, and method notes. Every entry names the source it came from and how that source was read; all are unreviewed candidates for the study team. With no parameter, returns the sources and counts. Nothing is written.",
                              _s({"parameter": {"type": "string"}, "guide_word": {"type": "string"}, "upstream_equipment": {"type": "array", "items": {"type": "string"}}})),
    "casebook_hazop_nodes": (t_hazop_nodes, "Derive draft HAZOP study nodes from a flowsheet topology: for each feed stream a node (the feed plus the pumps, compressors and valves on its line), the equipment tags for the rules store, which units each feed reaches (recycle loops marked), the standard deviation set, and watch values on product streams. Sources: a casebook case (case_id) or a loaded flowsheet session such as a P&ID extraction (session, plus the case_id that supplies the values). Never invents a size: sized deviations come out without one until you pass a sizes table that carries its reason. Warns when the topology is an unreviewed extraction, and reports reconcile findings and tag mismatches with the case. Writes nothing.",
                          _s({"case_id": {"type": "string"}, "session": {"type": "string"}, "study_id": {"type": "string"}, "sizes": {"type": "object"}})),
}
