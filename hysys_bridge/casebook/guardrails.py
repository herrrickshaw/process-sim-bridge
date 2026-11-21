"""Design-criteria guardrails evaluated on every simulated result (see studies/guardrails/rules.json and docs/PAPER_TO_SIMULATION_ARCHITECTURE.md section 21).
Rules: a rule is active only if its text was read from a public source or its numbers are supplied by the user with the clause and edition named. Nothing is taken
from memory. A guardrail reports; it never changes a simulation, a tolerance or a published number. Statuses: pass, violation, info, not-evaluated."""
from __future__ import annotations
import json, os

RULES_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "studies", "guardrails", "rules.json")
ACTIVE_TEXT = {"public-text-read", "user-supplied"}
LIMIT_KEYS = {"T_C": "C", "P_kPa": "kPa", "mass_kg_h": "kg/h"}
F30_K = 16.7                      # 30 F expressed in kelvin, 1910.106(a)(19)(iii) to (v)


def rules(path: str | None = None) -> dict:
    with open(path or RULES_PATH) as f: return {r["id"]: r for r in json.load(f)["rules"]}


def validate_limits(case: dict) -> list[str]:
    """Problems with a case's optional design_limits block (empty if absent)."""
    dl = case.get("design_limits")
    if dl is None: return []
    p, ids, units, comps = [], {s["id"] for s in case["streams"]}, {u["id"] for u in case["units"]}, set(case["basis"]["compounds"])
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    for sid, lim in (dl.get("streams") or {}).items():
        if sid not in ids: p.append(f"design_limits.streams.{sid}: not a stream"); continue
        if not (lim.get("anchor") or lim.get("assumed")): p.append(f"design_limits.streams.{sid}: needs an anchor (where the limit comes from) or an assumed reason")
        if not (set(lim) & set(LIMIT_KEYS)): p.append(f"design_limits.streams.{sid}: needs at least one of {sorted(LIMIT_KEYS)}")
        for k in set(lim) & set(LIMIT_KEYS):
            v = lim[k]
            if not (isinstance(v, dict) and set(v) <= {"min", "max"} and v and all(num(x) for x in v.values())): p.append(f"design_limits.streams.{sid}.{k} must be {{min and/or max: number}}")
            elif "min" in v and "max" in v and v["min"] > v["max"]: p.append(f"design_limits.streams.{sid}.{k}: min is above max")
    for c, d in (dl.get("compounds") or {}).items():
        if c not in comps: p.append(f"design_limits.compounds.{c}: not in basis.compounds"); continue
        if not (num(d.get("flash_point_C")) and num(d.get("boiling_point_C"))): p.append(f"design_limits.compounds.{c}: needs numeric flash_point_C and boiling_point_C")
        if not d.get("anchor"): p.append(f"design_limits.compounds.{c}: needs an anchor (the safety data sheet or table it came from)")
    for u, d in (dl.get("relief") or {}).items():
        if u not in units: p.append(f"design_limits.relief.{u}: not a unit"); continue
        if not (num(d.get("set_pressure_kPa")) and d["set_pressure_kPa"] > 0 and num(d.get("accumulation_pct")) and d["accumulation_pct"] >= 0): p.append(f"design_limits.relief.{u}: needs set_pressure_kPa > 0 and accumulation_pct >= 0")
        if not d.get("anchor"): p.append(f"design_limits.relief.{u}: needs an anchor naming the standard, clause and edition the accumulation comes from (licensed copy supplied by the user)")
        if d.get("stream") not in ids: p.append(f"design_limits.relief.{u}.stream must be the stream whose pressure is checked")
    return p


def category(flash_C: float, boil_C: float) -> tuple[str | None, str]:
    """OSHA 1910.106(a)(19): flammable liquid = flashpoint at or below 93 C; categories 1 to 4. None above 93 C."""
    if flash_C > 93: return None, "flashpoint above 93 C: not a flammable liquid under (a)(19)"
    if flash_C < 23: return ("1", "flashpoint below 23 C and boiling point at or below 35 C") if boil_C <= 35 else ("2", "flashpoint below 23 C and boiling point above 35 C")
    if flash_C <= 60: return "3", "flashpoint 23 to 60 C"
    return "4", "flashpoint above 60 C up to 93 C"


def _row(rule, status, obj, detail): return {"rule": rule, "status": status, "object": obj, "detail": detail}


def evaluate(case: dict, sim: dict[str, dict], scenario: str, rule_table: dict | None = None) -> list[dict]:
    """sim = {stream id: read_stream result} for every stream. Returns one row per rule and object."""
    R = rule_table or rules(); dl = case.get("design_limits") or {}; out = []
    def on(rid): return rid in R and R[rid]["text_status"] in ACTIVE_TEXT
    rid = "osha-1910.119-d2iD-safe-limits"
    if on(rid):
        lims = dl.get("streams") or {}
        if not lims: out.append(_row(rid, "not-evaluated", "-", "no safe limits declared in design_limits.streams"))
        for sid, lim in lims.items():
            for key, v in ((k, lim[k]) for k in LIMIT_KEYS if k in lim):
                got = sim[sid][{"T_C": "T", "P_kPa": "P", "mass_kg_h": "mass"}[key]]
                bad = ("min" in v and got < v["min"]) or ("max" in v and got > v["max"])
                out.append(_row(rid, "violation" if bad else "pass", sid, f"{key} {got:.4g} against {v}" ))
    rid = "osha-1910.119-d2iE-deviation-coverage"
    if on(rid) and scenario != "base":
        if not dl.get("streams"): out.append(_row(rid, "not-evaluated", "-", "scenarios are simulated but no safe limits are declared, so the deviations have no consequence criterion"))
    rid = "osha-1910.119-d3iG-material-balance"
    if on(rid):
        tol = R[rid].get("tolerance_rel", 0.001)
        mi = sum(sim[s["id"]]["mass"] for s in case["streams"] if s["role"] == "feed"); mo = sum(sim[s["id"]]["mass"] for s in case["streams"] if s["role"] == "product")
        rel = (mo - mi) / mi if mi else float("nan")
        out.append(_row(rid, "pass" if abs(rel) <= tol else "violation", "-", f"products {mo:.6g} kg/h against feeds {mi:.6g} kg/h ({100 * rel:+.4f} %, tool tolerance {100 * tol:.2f} %)"))
    rid = "osha-1910.106-a19-flammable-category"
    if on(rid):
        comp = dl.get("compounds") or {}
        if not comp: out.append(_row(rid, "not-evaluated", "-", "no flashpoint and boiling point declared in design_limits.compounds"))
        for s in case["streams"]:
            mf = sim[s["id"]].get("mass_fractions") or {}
            pure = next((c for c, w in mf.items() if w >= 0.999), None)
            if pure is None or pure not in comp:
                if comp and mf and sim[s["id"]]["mass"] > 0: out.append(_row(rid, "not-evaluated", s["id"], "mixture or compound without declared flashpoint"))
                continue
            fp, bp = comp[pure]["flash_point_C"], comp[pure]["boiling_point_C"]; cat, why = category(fp, bp); T = sim[s["id"]]["T"]
            near = T >= fp - F30_K
            if cat is None and not near: out.append(_row(rid, "info", s["id"], f"{pure}: {why}; stream {T:.1f} C is more than 30 F below its flashpoint")); continue
            out.append(_row(rid, "info", s["id"], f"{pure}: category {cat or 'none'} ({why}); stream {T:.1f} C {'is within 30 F (16.7 C) of or above its flashpoint {:.1f} C: handle as the next more hazardous category (1910.106(a)(19)(iii)-(v))'.format(fp) if near else 'is more than 30 F below its flashpoint'}"))
    rid = "api-520-521-relief-overpressure"
    relief = dl.get("relief") or {}
    if rid in R:
        if not relief: out.append(_row(rid, "not-evaluated", "-", "paywalled standard, not read; supply design_limits.relief with the clause and edition from a licensed copy to activate"))
        for u, d in relief.items():
            lim = d["set_pressure_kPa"] * (1 + d["accumulation_pct"] / 100); got = sim[d["stream"]]["P"]
            out.append(_row(rid, "violation" if got > lim else "pass", u, f"stream {d['stream']} {got:.4g} kPa against set {d['set_pressure_kPa']} x (1 + {d['accumulation_pct']} %) = {lim:.4g} kPa ({d['anchor']})"))
    return out


def summary(rows: list[dict]) -> dict:
    c = {}
    for r in rows: c[r["status"]] = c.get(r["status"], 0) + 1
    return c
