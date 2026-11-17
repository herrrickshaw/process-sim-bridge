"""Reconciliation: domain/business-rule checks on an extracted topology (the third stage of
Digitize-PID, arXiv 2109.03794: validate the digitised output against domain rules and correct).

Findings are Issues (same type as validate.py). `reconcile(fs, fix=True)` additionally applies
ONLY the corrections that cannot change process meaning, and logs each one:
  * drop self-loop streams (src == dst)            - detector artefact
  * drop isolated units (no streams at all)        - 'remove unconnected nodes' step of the merge pipeline
Everything else (OCR-confusable tags, wrong unit types, dead ends...) is reported for an engineer.
"""
from __future__ import annotations
import re
from collections import defaultdict
from .ir import Flowsheet
from .validate import Issue
from .extract_hmb import guess_unit_type

# (min_in, max_in, min_out, max_out); None = unbounded
DEGREE_RULES = {
    "mixer": (2, None, 1, 1), "splitter": (1, 1, 2, None),
    "pump": (1, 1, 1, 1), "compressor": (1, 1, 1, 1), "heater": (1, 1, 1, 1),
    "cooler": (1, 1, 1, 1), "valve": (1, 1, 1, 1),
    "separator": (1, None, 2, None), "column": (1, None, 2, None), "reactor": (1, None, 1, None),
}
# characters OCR / vision models commonly confuse
CONFUSE = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8", "Z": "2", "-": "", " ": "", "_": ""})


def _shape(tag: str) -> str:
    return re.sub(r"[A-Za-z]+", "A", re.sub(r"\d+", "9", tag))


def _components(fs: Flowsheet):
    adj = defaultdict(set)
    for s in fs.streams.values():
        if s.src in fs.units and s.dst in fs.units:
            adj[s.src].add(s.dst); adj[s.dst].add(s.src)
    seen, comps = set(), []
    for u in fs.units:
        if u in seen: continue
        stack, comp = [u], set()
        while stack:
            x = stack.pop()
            if x in comp: continue
            comp.add(x); stack.extend(adj[x] - comp)
        seen |= comp; comps.append(comp)
    return comps


def _sccs(fs: Flowsheet):
    """Tarjan (iterative-safe for flowsheet sizes via recursion limit guard)."""
    g = defaultdict(list)
    for s in fs.streams.values():
        if s.src in fs.units and s.dst in fs.units: g[s.src].append(s.dst)
    idx, low, on, st, out, c = {}, {}, set(), [], [], [0]
    import sys; sys.setrecursionlimit(max(1000, 10 * len(fs.units)))
    def strong(v):
        idx[v] = low[v] = c[0]; c[0] += 1; st.append(v); on.add(v)
        for w in g[v]:
            if w not in idx: strong(w); low[v] = min(low[v], low[w])
            elif w in on: low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            comp = []
            while True:
                w = st.pop(); on.discard(w); comp.append(w)
                if w == v: break
            out.append(comp)
    for v in fs.units:
        if v not in idx: strong(v)
    return [c for c in out if len(c) > 1]


def reconcile(fs: Flowsheet, fix: bool = False) -> tuple[list[Issue], list[str]]:
    issues: list[Issue] = []; actions: list[str] = []
    E = lambda w, m: issues.append(Issue("error", w, m))
    W = lambda w, m: issues.append(Issue("warn", w, m))

    for sid, s in list(fs.streams.items()):                      # 1 self loops, unknown ends
        if s.src is not None and s.src == s.dst:
            if fix: del fs.streams[sid]; actions.append(f"removed self-loop stream {sid} on {s.src}")
            else: E(sid, f"self-loop on {s.src}")
        for end in (s.src, s.dst):
            if end is not None and end not in fs.units: E(sid, f"references unknown unit {end!r}")
    fs.relink()

    touched = {x for s in fs.streams.values() for x in (s.src, s.dst) if x}      # 2 isolated units
    for uid in list(fs.units):
        if uid not in touched:
            if fix: del fs.units[uid]; actions.append(f"removed isolated unit {uid}")
            else: W(uid, "isolated unit: no streams attached")
    fs.relink()

    for uid, u in fs.units.items():                              # 3 tag vs type
        g = guess_unit_type(uid)
        if g != "unknown" and u.type not in ("unknown", g):
            W(uid, f"tag suggests {g} but type is {u.type}")

    by_type = defaultdict(list)                                  # 4 tag pattern consistency
    for uid, u in fs.units.items(): by_type[u.type].append(uid)
    for t, ids in by_type.items():
        if len(ids) >= 3:
            shapes = defaultdict(list)
            for i in ids: shapes[_shape(i)].append(i)
            major = max(shapes, key=lambda k: len(shapes[k]))
            if len(shapes[major]) > len(ids) / 2:
                for sh, members in shapes.items():
                    if sh != major:
                        for i in members: W(i, f"tag shape {sh!r} differs from other {t}s ({major!r}): possible OCR error")

    norm = defaultdict(list)                                     # 5 OCR-confusable near-duplicates
    for uid in fs.units: norm[uid.translate(CONFUSE).lower()].append(uid)
    for k, ids in norm.items():
        if len(ids) > 1: E(",".join(ids), "tags differ only by OCR-confusable characters (O/0, I/l/1, S/5, B/8) - likely one unit misread")

    for uid, u in fs.units.items():                              # 6 degree rules
        rule = DEGREE_RULES.get(u.type)
        if not rule: continue
        mi, xi, mo, xo = rule; ni, no = len(u.inlets), len(u.outlets)
        if ni < mi or (xi is not None and ni > xi) or no < mo or (xo is not None and no > xo):
            W(uid, f"{u.type} with {ni} inlet(s)/{no} outlet(s) violates the usual {mi}-{xi or 'n'} in / {mo}-{xo or 'n'} out")

    comps = _components(fs)                                      # 7 connectivity
    if len(comps) > 1:
        W("flowsheet", f"{len(comps)} disconnected sub-flowsheets: " + "; ".join("{" + ",".join(sorted(c)) + "}" for c in comps))
    for c in _sccs(fs):
        W("recycle", f"recycle loop through {sorted(c)}: HYSYS needs a Recycle block / tear stream here")
    feeds = [s.dst for s in fs.streams.values() if s.src is None and s.dst]
    prods = [s.src for s in fs.streams.values() if s.dst is None and s.src]
    if not feeds: W("flowsheet", "no feed stream (entering the diagram) found")
    if not prods: W("flowsheet", "no product stream (leaving the diagram) found")

    pairs = defaultdict(list)                                    # 8 duplicate parallel streams
    for sid, s in fs.streams.items():
        if s.src and s.dst: pairs[(s.src, s.dst)].append(sid)
    for (a, b), ids in pairs.items():
        if len(ids) > 1 and fs.units[a].type not in ("separator", "column", "splitter"):
            W(",".join(ids), f"{len(ids)} parallel streams {a}->{b}: possible double detection")
    return issues, actions
