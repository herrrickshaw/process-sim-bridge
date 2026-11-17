"""Score an extracted flowsheet (pred) against a ground-truth one, in the spirit of the
graph-level metrics of Stuermer et al. (arXiv 2411.13929, PID2Graph) and the adjacency-list
accuracy of Digitize-PID (arXiv 2109.03794).

Nodes = units, edges = directed unit->unit connections (a feed or product stream becomes an
edge from/to the pseudo-node FEED / PRODUCT so missing boundary streams are penalised).
Reported: node P/R/F1 (+ type accuracy), edge P/R/F1, undirected edge F1, direction-flip
count, and adjacency exact-match accuracy.

NOT reproduced: the papers' edge mAP. It ranks predictions by detector confidence and matches
nodes by bounding-box gIoU (Hungarian). This IR has neither geometry nor calibrated
confidences, so P/R/F1 are reported instead; do not compare the numbers to the papers' mAP.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from collections import Counter
from .ir import Flowsheet

FEED, PRODUCT = "<FEED>", "<PRODUCT>"


def hungarian(cost: list[list[float]]) -> list[tuple[int, int]]:
    """Minimum-cost assignment (rows<=cols or not; pads with zeros). O(n^3), stdlib only."""
    n = max(len(cost), len(cost[0]) if cost else 0)
    a = [[0.0] * (n + 1) for _ in range(n + 1)]
    for i, r in enumerate(cost):
        for j, c in enumerate(r): a[i + 1][j + 1] = c
    INF = float("inf"); u = [0.0] * (n + 1); v = [0.0] * (n + 1); p = [0] * (n + 1); way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i; j0 = 0; minv = [INF] * (n + 1); used = [False] * (n + 1)
        while True:
            used[j0] = True; i0 = p[j0]; delta = INF; j1 = 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = a[i0][j] - u[i0] - v[j]
                    if cur < minv[j]: minv[j], way[j] = cur, j0
                    if minv[j] < delta: delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]: u[p[j]] += delta; v[j] -= delta
                else: minv[j] -= delta
            j0 = j1
            if p[j0] == 0: break
        while j0:
            j1 = way[j0]; p[j0] = p[j1]; j0 = j1
    return [(p[j] - 1, j - 1) for j in range(1, n + 1)
            if p[j] and p[j] - 1 < len(cost) and cost[0] and j - 1 < len(cost[0])]


def edges(fs: Flowsheet) -> list[tuple[str, str]]:
    return [(s.src or FEED, s.dst or PRODUCT) for s in fs.streams.values()]


def _degrees(fs: Flowsheet):
    d = Counter()
    for a, b in edges(fs):
        d[a] += 1; d[b] += 1
    return d


def match_nodes(pred: Flowsheet, truth: Flowsheet, mode: str = "id") -> dict[str, str]:
    """pred unit id -> truth unit id.
    mode 'id': identical ids only (use when tags were read correctly).
    mode 'structure': ids ignored; assignment by unit type + degree (for drawings whose tags
    were invented/misread). Structure matching is a weak heuristic - state it when reporting."""
    if mode == "id":
        return {u: u for u in pred.units if u in truth.units}
    pu, tu = list(pred.units), list(truth.units)
    dp, dt = _degrees(pred), _degrees(truth)
    cost = [[(0.0 if pred.units[a].type == truth.units[b].type else 1.0) + 0.25 * abs(dp[a] - dt[b])
             for b in tu] for a in pu]
    return {pu[i]: tu[j] for i, j in hungarian(cost)} if pu and tu else {}


@dataclass
class Score:
    node_p: float; node_r: float; node_f1: float; type_acc: float
    edge_p: float; edge_r: float; edge_f1: float; undirected_f1: float
    direction_flips: int; adjacency_acc: float
    matching: str = "id"

    def __str__(self):
        return (f"[matching={self.matching}] nodes P/R/F1 {self.node_p:.2f}/{self.node_r:.2f}/{self.node_f1:.2f} "
                f"(type acc {self.type_acc:.2f}) | edges P/R/F1 {self.edge_p:.2f}/{self.edge_r:.2f}/{self.edge_f1:.2f} "
                f"(undirected F1 {self.undirected_f1:.2f}, {self.direction_flips} direction flips) | "
                f"adjacency exact-match {self.adjacency_acc:.2f}")


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0 if fn == 0 else 0.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def _mset(edge_list, undirected=False):
    return Counter(tuple(sorted(e)) if undirected else e for e in edge_list)


def score(pred: Flowsheet, truth: Flowsheet, mode: str = "id") -> Score:
    m = match_nodes(pred, truth, mode)
    tp_n = len(m); np_, nt = len(pred.units), len(truth.units)
    node_p, node_r, node_f = _prf(tp_n, np_ - tp_n, nt - tp_n)
    type_acc = (sum(pred.units[a].type == truth.units[b].type for a, b in m.items()) / tp_n) if tp_n else 0.0
    rev = lambda x: m.get(x, "?" + x) if x not in (FEED, PRODUCT) else x     # unmatched stay unmatched
    pe = [(rev(a), rev(b)) for a, b in edges(pred)]
    te = edges(truth)
    def cmp(P, T):
        tp = sum((P & T).values()); return tp, sum(P.values()) - tp, sum(T.values()) - tp
    ep, er, ef = _prf(*cmp(_mset(pe), _mset(te)))
    _, _, uf = _prf(*cmp(_mset(pe, True), _mset(te, True)))
    flips = sum(((_mset(pe, True) & _mset(te, True)).values())) - sum((_mset(pe) & _mset(te)).values())
    # adjacency exact match over truth units: same set of (direction, neighbour)
    def adj(es):
        d: dict[str, set] = {}
        for a, b in es:
            if a not in (FEED, PRODUCT): d.setdefault(a, set()).add(("out", b))
            if b not in (FEED, PRODUCT): d.setdefault(b, set()).add(("in", a))
        return d
    ap_, at_ = adj(pe), adj(te)
    acc = sum(ap_.get(u, set()) == at_.get(u, set()) for u in truth.units) / nt if nt else 1.0
    return Score(node_p, node_r, node_f, type_acc, ep, er, ef, uf, max(flips, 0), acc, mode)


if __name__ == "__main__":
    import sys
    pred, truth = Flowsheet.from_json(sys.argv[1]), Flowsheet.from_json(sys.argv[2])
    print(score(pred, truth, sys.argv[3] if len(sys.argv) > 3 else "id"))
