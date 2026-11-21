"""Draft HAZOP study nodes derived from a flowsheet topology (a casebook case, or a flowsheet extracted from a P&ID).
What it does: for every feed stream it builds a node (the feed plus the line equipment that follows it: pumps, compressors, valves), lists the equipment tags that can
cause a deviation on that line (for the rules store), works out which units each feed can reach (including units inside recycle loops), proposes the standard deviation
set, proposes the values to watch on product streams, and reports what it could not establish.
What it never does: invent a size. A MORE or LESS deviation comes out without a size, so the draft does not validate until the team supplies sizes and the reason for them
(or passes a sizes table that carries its own reason). Controllers and instrument loops are not in the topology, so 'controller' causes are never derived. The draft is
unreviewed: when the topology comes from a P&ID extraction (units flagged needs-signoff) the draft says so and carries the reconcile findings.
Deviations are applied at feed streams only (the runner's rule); an intermediate stream is covered by propagation, and the unit table says which feeds reach it."""
from __future__ import annotations
import re
from collections import deque
from . import schema

LINE_TYPES = {"pump", "compressor", "valve"}                                   # pass-through line equipment that stays inside a feed's node
EQUIPMENT_TAG = {"pump": "pump", "compressor": "pump", "valve": "valve", "heater": "heater", "cooler": "exchanger", "exchanger": "exchanger"}
STANDARD = {"flow": ["NONE", "MORE", "LESS", "REVERSE"], "temperature": ["MORE", "LESS"], "pressure": ["MORE", "LESS"]}
SIZE_KIND = {"flow": ("relative", "absolute"), "temperature": ("absolute",), "pressure": ("relative", "absolute")}
WATCH = ("T", "mass", "vapor_fraction")


def graph_from_case(case: dict) -> dict:
    return {"name": case["id"], "units": {u["id"]: {"type": u["type"], "flags": []} for u in case["units"]},
            "streams": {s["id"]: {"role": s["role"], "src": s.get("src"), "dst": s.get("dst")} for s in case["streams"]}, "origin": "casebook case"}


def graph_from_flowsheet(fs) -> dict:
    return {"name": fs.name, "units": {u.id: {"type": u.type, "flags": list(u.flags)} for u in fs.units.values()},
            "streams": {s.id: {"role": s.kind, "src": s.src, "dst": s.dst} for s in fs.streams.values()}, "origin": "flowsheet (P&ID extraction or other)"}


def _slug(x: str) -> str: return re.sub(r"[^a-z0-9]+", "-", x.lower()).strip("-")


def _downstream(g, start_unit):
    """Units reachable from a unit along streams, and whether the start unit lies on a cycle."""
    out_of = {}
    for sid, s in g["streams"].items():
        if s["src"] in g["units"] and s["dst"] in g["units"]: out_of.setdefault(s["src"], []).append(s["dst"])
    seen, q, cyc = set(), deque([start_unit]), False
    while q:
        u = q.popleft()
        if u in seen: continue
        seen.add(u); q.extend(out_of.get(u, []))
    return seen


def _line(g, feed_stream):
    """Units of the node's line: from the feed's destination through single-inlet single-outlet pass-through equipment, ending with the first process unit (included)."""
    chain, u = [], g["streams"][feed_stream]["dst"]
    ins = lambda x: [sid for sid, s in g["streams"].items() if s["dst"] == x]
    outs = lambda x: [sid for sid, s in g["streams"].items() if s["src"] == x]
    while u in g["units"]:
        chain.append(u)
        if g["units"][u]["type"] not in LINE_TYPES or len(ins(u)) != 1 or len(outs(u)) != 1: break
        nxt = g["streams"][outs(u)[0]]["dst"]
        if nxt is None or nxt in chain: break
        u = nxt
    return chain


def match_case(g: dict, case: dict) -> list[str]:
    """Do the topology's tags match the casebook case that will supply the values? Mismatches mean the study cannot run until the tags are reconciled."""
    p, cs, cu = [], {s["id"]: s for s in case["streams"]}, {u["id"]: u for u in case["units"]}
    for sid, s in g["streams"].items():
        if s["role"] == "feed" and (sid not in cs or cs[sid]["role"] != "feed"): p.append(f"feed {sid} is not a feed stream of case {case['id']}")
    for sid, s in cs.items():
        if s["role"] == "feed" and not (sid in g["streams"] and g["streams"][sid]["role"] == "feed"): p.append(f"feed {sid} of the case is not a feed in the topology")
    for uid, u in g["units"].items():
        if uid not in cu: p.append(f"unit {uid} is not in case {case['id']}")
        elif cu[uid]["type"] != u["type"]: p.append(f"unit {uid} is a {u['type']} in the topology and a {cu[uid]['type']} in the case")
    p += [f"unit {uid} of the case is not in the topology" for uid in cu if uid not in g["units"]]
    return p


def derive(g: dict, case: dict | None = None, study_id: str = "draft-study", sizes: dict | None = None, issues: list[str] | None = None) -> dict:
    """The draft study spec. `sizes` = {"reason": str, "flow": {"MORE": {"relative": x}, ...}, ...} supplied by the team; without it every sized deviation is left without a size."""
    sizes = sizes or {}
    if sizes and not (isinstance(sizes.get("reason"), str) and sizes["reason"].strip()): raise ValueError("a sizes table needs a reason (the team's basis for the sizes); sizes are never invented")
    feeds = [sid for sid, s in g["streams"].items() if s["role"] == "feed"]; warnings, errors = [], []
    for sid in feeds:
        s = g["streams"][sid]
        if s["src"] is not None: errors.append(f"feed {sid} has a source unit {s['src']}: not a feed")
        if s["dst"] not in g["units"]: warnings.append(f"feed {sid} does not enter any unit: no node derived")
    feeds = [sid for sid in feeds if g["streams"][sid]["dst"] in g["units"]]
    nodes, exposure, missing = [], {uid: [] for uid in g["units"]}, []
    for sid in feeds:
        chain = _line(g, sid); tags = sorted({EQUIPMENT_TAG[g["units"][u]["type"]] for u in chain if g["units"][u]["type"] in EQUIPMENT_TAG})      # every unit of the node line, the first process unit included: a deviation at the feed stands for one anywhere on the line
        reach = _downstream(g, g["streams"][sid]["dst"])
        for u in reach: exposure[u].append(sid)
        nid = "node-" + _slug(sid); devs = []
        for par, words in STANDARD.items():
            for gw in words:
                d = {"id": f"{_slug(sid)}-{par}-{_slug(gw)}", "parameter": par, "guide_word": gw}
                if gw in ("MORE", "LESS"):
                    sz = (sizes.get(par) or {}).get(gw)
                    if sz and len(sz) == 1 and set(sz) <= set(SIZE_KIND[par]): d["size"] = dict(sz); d["assumed"] = sizes["reason"]
                    else: d["size"] = None; d["needs"] = "size and the reason for it"; missing.append(d["id"])
                devs.append(d)
        label = " -> ".join([sid] + [f"{u} ({g['units'][u]['type']})" for u in chain])
        nodes.append({"id": nid, "description": f"feed line {label}", "stream": sid, "upstream_equipment": tags, "deviations": devs,
                      "line_units": chain})
    # recycle: a unit is in a loop if it can reach itself
    out_of = {}
    for s in g["streams"].values():
        if s["src"] in g["units"] and s["dst"] in g["units"]: out_of.setdefault(s["src"], []).append(s["dst"])
    in_loop = sorted(u for u in g["units"] if any(u in _downstream(g, nx) for nx in out_of.get(u, [])))
    products = [sid for sid, s in g["streams"].items() if s["role"] == "product"]
    watch = [{"stream": sid, "property": p} for sid in products for p in WATCH]
    flagged = sorted(u for u, x in g["units"].items() if "needs-signoff" in x["flags"])
    if flagged: warnings.append(f"the topology comes from an unreviewed P&ID extraction: {len(flagged)} unit(s) are flagged needs-signoff; an engineer must confirm the topology before the draft is used")
    if issues: warnings.append(f"reconcile reports {len(issues)} finding(s) on the topology: " + "; ".join(issues[:5]) + (" ..." if len(issues) > 5 else ""))
    if in_loop: warnings.append(f"units in recycle loops: {', '.join(in_loop)}; a deviation on a feed propagates through the loop and the solver may need a better starting point")
    if not nodes: warnings.append("no node derived: the flowsheet has no feed stream entering a unit")
    mismatches = match_case(g, case) if case else ["no casebook case given: the spec's `case` is empty until you name the case that supplies the values"]
    if case:
        cap = schema.capability(case)
        if not cap["buildable"]: warnings.append(f"the case cannot be run on the DWSIM backend (unverified unit types {cap['unverified_unit_types']}): the study can be drafted but not run")
    if sizes: warnings.append("sizes were supplied by the team with the reason: " + sizes["reason"])
    return {"id": study_id, "case": case["id"] if case else None, "draft": True, "nodes": nodes, "watch": watch,
            "derivation": {"from": g["origin"], "topology": g["name"], "complete": not missing and not mismatches and not errors, "missing_sizes": missing, "mismatches": mismatches, "errors": errors, "warnings": warnings,
                           "units": {uid: {"type": x["type"], "reached_by_feeds": sorted(exposure[uid]), "in_recycle": uid in in_loop, "needs_signoff": "needs-signoff" in x["flags"]} for uid, x in g["units"].items()},
                           "limits": "controllers and instrument loops are not in the topology, so no controller cause is derived; deviations are applied at feeds only; composition deviations need a named compound and a fraction and are not proposed; sizes and causes are the team's"}}
