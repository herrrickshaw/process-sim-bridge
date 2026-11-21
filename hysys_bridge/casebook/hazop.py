"""HAZOP deviation runner: guide word + parameter + SIZE on a feed stream of a casebook case, solved on DWSIM, with the consequences read from the simulation and
from the guardrails (declared safe limits, material balance, advisory rules). Design rules, as everywhere in the casebook:
- a deviation's size is never invented by the tool: every MORE or LESS needs a size and a reason for it (anchor or assumed), supplied by the study team;
- causes and safeguards are the team's words, carried through to the worksheet; the tool assigns no severity, likelihood, ranking or recommendation;
- consequences are what a STEADY-STATE flowsheet shows: changes in watched values, new guardrail violations against the declared limits, and a deviation that
  has no steady-state solution. Transients, relief behaviour and anything dynamic are not evaluated, and the worksheet says so;
- REVERSE flow cannot be represented in a steady-state flowsheet and is reported as not evaluable, never as 'no consequence';
- NONE flow is run as a flow of NONE_FLOW_FRACTION of the design flow, because a zero flow cannot be solved (a tool choice, stated in the worksheet).
Quantitative guide words (NONE, MORE, LESS, REVERSE) follow the simulation-based HAZOP literature in docs/HAZOP_WITH_SIMULATION_LITERATURE.md: the deviation
must be sized, not only named."""
from __future__ import annotations
import copy, re
from . import guardrails, hazop_rules, runner, schema

NONE_FLOW_FRACTION = 1e-4
ALLOWED = {"flow": {"NONE", "MORE", "LESS", "REVERSE"}, "temperature": {"MORE", "LESS"}, "pressure": {"MORE", "LESS"}, "composition": {"AS_WELL_AS", "PART_OF"}}
WATCH_PROPS = {"T": "C", "P": "kPa", "mass": "kg/h", "vapor_fraction": "-"}
NOTE = ("Steady-state simulation only. Causes and safeguards are the study team's input; the tool assigns no severity, likelihood or recommendation. "
        "Consequences are changes the flowsheet shows and violations of the declared limits; transients, relief behaviour and dynamics are not evaluated.")


def _size_problems(pa, dev) -> list[str]:
    p, gw, par, sz = [], dev.get("guide_word"), dev.get("parameter"), dev.get("size")
    if gw in ("NONE", "REVERSE"):
        if sz is not None: p.append(f"{pa}: {gw} takes no size")
        return p
    if not (dev.get("anchor") or dev.get("assumed")): p.append(f"{pa}: a sized deviation needs an anchor or an assumed reason for its size (the tool never invents sizes)")
    if par == "composition":
        if not dev.get("compound"): p.append(f"{pa}: composition deviations need a compound")
        num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
        if gw == "AS_WELL_AS" and not (isinstance(sz, dict) and set(sz) == {"fraction"} and num(sz["fraction"]) and 0 < sz["fraction"] < 1): p.append(f"{pa}: AS_WELL_AS needs size {{fraction: 0..1 exclusive}} (in the case's composition basis)")
        if gw == "PART_OF" and not (isinstance(sz, dict) and set(sz) == {"relative"} and num(sz["relative"]) and 0 < sz["relative"] <= 1): p.append(f"{pa}: PART_OF needs size {{relative: (0, 1]}}")
        return p
    if not (isinstance(sz, dict) and len(sz) == 1 and set(sz) <= {"relative", "absolute"} and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in sz.values())): p.append(f"{pa}: size must be {{relative: x}} or {{absolute: x}} with x > 0")
    elif par == "temperature" and "relative" in sz: p.append(f"{pa}: a relative temperature change is meaningless; give {{absolute: degrees C}}")
    elif "relative" in sz and gw == "LESS" and sz["relative"] >= 1: p.append(f"{pa}: LESS by 100 percent or more removes the quantity; use NONE for flow")
    return p


def validate_spec(spec: dict, case: dict) -> list[str]:
    p = []
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(spec.get("id", ""))): p.append("id must be lowercase letters, digits and hyphens")
    if spec.get("case") != case.get("id"): p.append(f"spec.case {spec.get('case')!r} is not this case ({case.get('id')!r})")
    feeds = {s["id"] for s in case["streams"] if s["role"] == "feed"}; ids = {s["id"] for s in case["streams"]}
    if not spec.get("nodes"): p.append("nodes is empty")
    seen, nodes = set(), set()
    for n in spec.get("nodes", []):
        nid = n.get("id", "?")
        if nid in nodes: p.append(f"node {nid}: duplicated")
        nodes.add(nid)
        if n.get("stream") not in feeds: p.append(f"node {nid}: stream {n.get('stream')!r} is not a feed stream (deviations are applied to feeds: {sorted(feeds)})")
        if not n.get("deviations"): p.append(f"node {nid}: no deviations")
        ue = n.get("upstream_equipment")
        if ue is not None and not (isinstance(ue, list) and set(ue) <= hazop_rules.EQUIPMENT): p.append(f"node {nid}: upstream_equipment must be a list drawn from {sorted(hazop_rules.EQUIPMENT)}")
        for d in n.get("deviations", []):
            pa = f"node {nid} deviation {d.get('id', '?')}"
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(d.get("id", ""))) or d["id"] in seen: p.append(f"{pa}: id missing, malformed or duplicated")
            seen.add(d.get("id"))
            if d.get("parameter") not in ALLOWED or d.get("guide_word") not in ALLOWED.get(d.get("parameter"), set()):
                p.append(f"{pa}: {d.get('guide_word')!r} on {d.get('parameter')!r} is not supported; allowed: {({k: sorted(v) for k, v in ALLOWED.items()})}"); continue
            p += _size_problems(pa, d)
            if d["parameter"] == "composition" and d.get("compound") not in case["basis"]["compounds"]: p.append(f"{pa}: compound {d.get('compound')!r} is not in the case's compounds")
            if "safeguards" in d and not (isinstance(d["safeguards"], list) and all(isinstance(x, str) for x in d["safeguards"])): p.append(f"{pa}: safeguards must be a list of strings")
    for w in spec.get("watch", []):
        if w.get("stream") not in ids or w.get("property") not in WATCH_PROPS: p.append(f"watch {w}: stream must be in the case and property one of {sorted(WATCH_PROPS)}")
    pk = spec.get("packages")
    if pk is not None and (not pk or set(pk) - set(case["basis"]["packages"])): p.append(f"packages must be a non-empty subset of {case['basis']['packages']}")
    if "design_limits" in spec: p += guardrails.validate_limits({**case, "design_limits": spec["design_limits"]})
    return p


def apply_deviation(case: dict, stream: str, dev: dict) -> tuple[dict, dict]:
    """A copy of the case with the deviation applied to the named feed stream, and a record of what changed."""
    c = copy.deepcopy(case); s = next(x for x in c["streams"] if x["id"] == stream); par, gw, sz = dev["parameter"], dev["guide_word"], dev.get("size") or {}
    sign = 1 if gw == "MORE" else -1
    if par == "flow":
        q = s["mass_flow"]; before = q["value"]
        q["value"] = before * NONE_FLOW_FRACTION if gw == "NONE" else before * (1 + sign * sz["relative"]) if "relative" in sz else before + sign * sz["absolute"]
        if q["value"] <= 0: raise ValueError(f"deviation {dev['id']} leaves no flow on {stream}; use NONE")
        return c, {"stream": stream, "quantity": "mass flow", "before": before, "after": q["value"], "unit": "kg/h", "note": f"NONE is run as {NONE_FLOW_FRACTION:g} of the design flow (zero flow cannot be solved)" if gw == "NONE" else None}
    if par == "temperature":
        q = s["T"]; before = q["value"]; q["value"] = before + sign * sz["absolute"]
        return c, {"stream": stream, "quantity": "temperature", "before": before, "after": q["value"], "unit": "C", "note": None}
    if par == "pressure":
        q = s["P"]; before = q["value"]
        delta = sz["absolute"] / (100.0 if q["unit"] == "bar" else 1.0) if "absolute" in sz else before * sz["relative"]
        q["value"] = before + sign * delta
        if q["value"] <= 0 and q.get("basis") == "absolute": raise ValueError(f"deviation {dev['id']} makes the pressure on {stream} non-positive")
        return c, {"stream": stream, "quantity": "pressure", "before": before, "after": q["value"], "unit": q["unit"], "note": f"relative sizes apply to the stored value in its stated basis ({q.get('basis')}); absolute sizes are kPa"}
    v = s["composition"]["values"]; comp = dev["compound"]; before = v[comp]
    if gw == "AS_WELL_AS": v2 = {k: x * (1 - sz["fraction"]) for k, x in v.items()}; v2[comp] = v[comp] * (1 - sz["fraction"]) + sz["fraction"]
    else:
        keep = v[comp] * (1 - sz["relative"]); rest = 1 - v[comp]
        if rest <= 0: raise ValueError(f"deviation {dev['id']}: {comp} is the whole stream")
        v2 = {k: x * (1 - keep) / rest for k, x in v.items()}; v2[comp] = keep
    tot = sum(v2.values()); s["composition"]["values"] = {k: x / tot for k, x in v2.items()}
    s["composition"]["provenance"] = {k: ("assumed" if k == comp else w) for k, w in s["composition"]["provenance"].items()}
    return c, {"stream": stream, "quantity": f"fraction of {comp}", "before": before, "after": s["composition"]["values"][comp], "unit": "-", "note": "in the case's composition basis"}


def _watch(spec, base, dev):
    out = []
    for w in spec.get("watch", []):
        key = {"T": "T", "P": "P", "mass": "mass", "vapor_fraction": "vapor_fraction"}[w["property"]]; b, d = base["sim"][w["stream"]].get(key), dev["sim"][w["stream"]].get(key)
        out.append({"stream": w["stream"], "property": w["property"], "unit": WATCH_PROPS[w["property"]], "baseline": b, "deviated": d, "delta": None if b is None or d is None else d - b})
    return out


def _why(res: dict) -> str:
    """A short reason for a failed solve: the solver's error strings and finding codes, not the raw response."""
    w = res.get("why") or {}; errs = [e for e in (w.get("errors") or [])][:2]; codes = sorted({f.get("code") for f in (res.get("findings") or []) if f.get("code")})
    parts = (errs or ([w["blocked"]] if w.get("blocked") else [])) + ([f"findings {', '.join(codes)}"] if codes else [])
    return "; ".join(parts) or str(res.get("reason") or w)


def _consequences(base_rows, dev_rows, dev_res) -> list[dict]:
    key = lambda r: (r["rule"], r["object"]); before = {key(r): r["status"] for r in base_rows}; out = []
    for r in dev_rows:
        if r["status"] in ("violation", "advisory"):
            was = before.get(key(r)); out.append({"kind": "limit_violation" if r["status"] == "violation" else "advisory", "rule": r["rule"], "object": r["object"], "text": r["detail"], "new": was != r["status"]})
    for f in dev_res.get("findings", []):
        if f.get("severity") in ("blocker", "warning"): out.append({"kind": "solver_finding", "rule": f["code"], "object": f["object"], "text": f"{f['severity']}: {f.get('simulator_fix') or ''}".strip(), "new": True})
    return out


def run_study(spec: dict, case: dict, transport_factory=None, solve=None, rules=None) -> dict:
    """Run every deviation of a validated spec in every package; returns the worksheet. `solve` is injectable for tests (default: runner.solve_case)."""
    probs = validate_spec(spec, case)
    if probs: raise ValueError("spec is not valid: " + "; ".join(probs))
    solve = solve or (lambda c, pk: runner.solve_case(c, pk, transport_factory))
    limits = spec.get("design_limits", case.get("design_limits")); base_case = {**copy.deepcopy(case), "design_limits": limits} if limits else copy.deepcopy(case)
    packages = spec.get("packages") or [case["basis"]["package_in_paper"]]; rows, warnings = [], []
    use_rules = spec.get("suggestions", True); store = None
    if use_rules:
        store = rules or hazop_rules.load(); rp = hazop_rules.validate(store)
        if rp: raise ValueError("the rules store is not valid: " + "; ".join(rp))
    if not (limits or {}).get("streams"): warnings.append("no safe limits are declared for any stream: consequences show simulated changes only; OSHA 1910.119(d)(2)(i)(D) has no criterion to evaluate (see the guardrail registry)")
    gaps = [{"node": n["id"], "parameters_without_a_deviation": sorted(set(ALLOWED) - {d["parameter"] for d in n["deviations"]})} for n in spec["nodes"] if set(ALLOWED) - {d["parameter"] for d in n["deviations"]}]
    for pk in packages:
        base = solve(base_case, pk)
        if not base.get("ran") or not base.get("solved"): raise RuntimeError(f"the undeviated case does not solve in {pk}: {base.get('reason') or base.get('why')}")
        base_guard = guardrails.evaluate(base_case, base["sim"], "base")
        for n in spec["nodes"]:
            for d in n["deviations"]:
                row = {"deviation_id": d["id"], "node": n["id"], "node_description": n.get("description"), "stream": n["stream"], "parameter": d["parameter"], "guide_word": d["guide_word"], "package": pk,
                       "cause": d.get("cause"), "safeguards": d.get("safeguards", []), "size": d.get("size"), "size_source": d.get("anchor") or d.get("assumed"),
                       "suggested": hazop_rules.suggest(store, d["parameter"], d["guide_word"], n.get("upstream_equipment")) if use_rules else None}
                if d["guide_word"] == "REVERSE":
                    rows.append({**row, "evaluable": False, "solved": None, "applied": None, "watch": [], "consequences": [{"kind": "not_evaluable", "text": "reverse flow cannot be represented in a steady-state flowsheet; assess it by another method", "new": True}]}); continue
                dc, applied = apply_deviation(base_case, n["stream"], d); res = solve(dc, pk)
                if not res.get("solved"):
                    rows.append({**row, "evaluable": True, "solved": False, "applied": applied, "watch": [], "consequences": [{"kind": "no_solution", "text": f"no steady-state solution at the deviated condition: {_why(res)}", "new": True}]}); continue
                guard = guardrails.evaluate(dc, res["sim"], d["id"])
                rows.append({**row, "evaluable": True, "solved": True, "applied": applied, "watch": _watch(spec, base, res), "consequences": _consequences(base_guard, guard, res)})
    return {"study": spec["id"], "case": case["id"], "case_hash": schema.case_hash(case), "packages": packages, "none_flow_fraction": NONE_FLOW_FRACTION, "rows": rows, "gaps": gaps, "warnings": warnings, "note": NOTE, "about": spec.get("about"),
            "rules": None if not use_rules else {"sources": [x for x in store["sources"]], "method_notes": store.get("method_notes", []), "mapping_note": "causes the source lists for 'other composition than usual' are offered for both AS_WELL_AS and PART_OF (this tool's mapping)", "status": "every suggestion is a candidate for the study team and is unreviewed"},
            "summary": {"deviations": len(rows), "not_evaluable": sum(r["evaluable"] is False for r in rows), "no_solution": sum(r["solved"] is False for r in rows),
                        "with_new_violation": sum(any(c["kind"] == "limit_violation" and c["new"] for c in r["consequences"]) for r in rows)}}


def _sug(r) -> str:
    sg = r.get("suggested")
    if not sg: return ""
    c = "; ".join(x["text"] for x in sg["causes"]); t = "; ".join(x["text"] for x in sg["safeguard_types"])
    return (f"causes: {c}" if c else "") + (" / " if c and t else "") + (f"safeguard types: {t}" if t else "")


def render_markdown(ws: dict) -> str:
    L = [f"# HAZOP deviation worksheet: {ws['study']} (case {ws['case']}, hash {ws['case_hash']})", "", f"> {ws['note']}", ""]
    if ws.get("about"): L += [f"> **About this study:** {ws['about']}", ""]
    L += [f"**Warning:** {w}" for w in ws["warnings"]]; L += [f"**Coverage gap:** node {g['node']} has no deviation for {', '.join(g['parameters_without_a_deviation'])}" for g in ws["gaps"]]
    L += ["", "| Node | Deviation | Package | Applied | Cause (team) | Consequences (simulation) | Safeguards (team) | Suggestions (rules store, unreviewed) |", "|---|---|---|---|---|---|---|---|"]
    for r in ws["rows"]:
        ap = f"{r['applied']['quantity']} {r['applied']['before']:.4g} to {r['applied']['after']:.4g} {r['applied']['unit']}" if r["applied"] else "-"
        cons = "; ".join(f"{c['kind']}: {c['text']}" + ("" if c["new"] else " (already in the baseline)") for c in r["consequences"]) or "no new violation or finding"
        watch = "; ".join(f"{w['stream']} {w['property']} {w['baseline']:.4g} to {w['deviated']:.4g}" for w in r["watch"] if w["baseline"] is not None and w["deviated"] is not None)
        L.append(f"| {r['node']} | {r['guide_word']} {r['parameter']} ({r['stream']}) | {r['package']} | {ap} | {r['cause'] or ''} | {cons}{' [' + watch + ']' if watch else ''} | {'; '.join(r['safeguards'])} | {_sug(r)} |")
    if ws.get("rules"):
        L += ["", "**Sources of the suggestions** (candidates for the team, none reviewed):"] + [f"- {x['title']} ({x['url']}); {x['how_read']}; licence: {x['licence']}" for x in ws["rules"]["sources"]]
        L += [f"- Method note: {m['text']}" for m in ws["rules"]["method_notes"]] + [f"- Mapping: {ws['rules']['mapping_note']}"]
    s = ws["summary"]; L += ["", f"{s['deviations']} deviations: {s['with_new_violation']} with a new limit violation, {s['no_solution']} without a steady-state solution, {s['not_evaluable']} not evaluable."]
    return "\n".join(L)
