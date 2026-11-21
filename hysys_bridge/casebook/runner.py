"""Run a case on DWSIM for each property package and compare with the published numbers. No tuning: the only thing varied is the package."""
from __future__ import annotations
import os, shlex
from .. import hysys_writer
from ..dwsim.backend import DwsimBackend, StdioTransport
from . import diagnose, guardrails, schema


def default_transport():
    cmd = os.environ.get("DWSIM_MCP_CMD")
    if not cmd: raise RuntimeError("DWSIM_MCP_CMD is not set (operator-set, e.g. 'podman run -i --rm --network none ghcr.io/danwbr/dwsim-mcp:latest --stdio')")
    return StdioTransport(shlex.split(cmd))


def _simulated(r, fs, be, cache, mm=None):
    rs = lambda sid: cache.setdefault(sid, be.read_stream(sid))
    def duty(uid):
        u = fs.units[uid]
        if u.type in schema.REACTORS: return be.reactor_duty_kJ_h(uid)            # includes the heat of reaction, which stream enthalpies do not
        a, b = rs(u.inlets[0]), rs(u.outlets[0])
        if a["h_kJ_kg"] is None or b["h_kJ_kg"] is None: raise RuntimeError("DWSIM returned no enthalpy for the unit's streams")
        return (b["h_kJ_kg"] - a["h_kJ_kg"]) * a["mass"]                         # kJ/h from the stream enthalpies (the server has no unit-duty result)
    if r["kind"] == "unit_duty": return duty(r["target"])
    if r["kind"] == "units_duty_sum_kJ_h": return sum(duty(u) for u in r["targets"])
    if r["kind"] == "streams_mass_sum_kg_h": return sum(rs(t)["mass"] for t in r["targets"])
    if r["kind"] == "stream_mole_fraction":                                    # DWSIM returns mass fractions: convert with the case's own molar masses
        mf = rs(r["target"])["mass_fractions"]
        if r["compound"] not in mf or not mm or set(mf) - set(mm): raise RuntimeError(f"cannot convert to a mole fraction of {r['compound']}: need DWSIM's mass fractions and a molar mass for every compound")
        n = {c: w / mm[c] for c, w in mf.items()}; return n[r["compound"]] / sum(n.values())
    if r["kind"] == "stream_mass_fraction":
        mf = rs(r["target"])["mass_fractions"]
        if r["compound"] not in mf: raise RuntimeError(f"DWSIM returned no mass fraction of {r['compound']} for {r['target']}")
        return mf[r["compound"]]
    v = rs(r["target"])[{"stream_T_C": "T", "stream_P_kPa": "P", "stream_mass_kg_h": "mass", "stream_vapor_fraction": "vapor_fraction"}[r["kind"]]]
    if v is None: raise RuntimeError(f"DWSIM returned no {r['kind']} for {r['target']}")
    return v


def compare(reported: float, simulated: float, pass_rel: float) -> dict:
    rel = (simulated - reported) / abs(reported) if reported else None
    return {"reported": reported, "simulated": simulated, "rel_err": rel, "within_tol": rel is not None and abs(rel) <= pass_rel}


def compare_item(r: dict, simulated: float, default_pass_rel: float) -> dict:
    """One reported value: a point (relative error against its tolerance, the item's own pass_rel if it has one) or a published range (inside it, inclusive)."""
    if "range" in r:
        lo, hi = r["range"]; return {"range": [lo, hi], "reported": None, "simulated": simulated, "rel_err": None, "within_tol": lo <= simulated <= hi}
    return compare(r["value"], simulated, r.get("pass_rel", default_pass_rel))


def run_case(case: dict, transport_factory=None, packages: list[str] | None = None, scenarios: list[str] | None = None) -> dict:
    cap = schema.capability(case)
    if not cap["buildable"]: return {"case": case["id"], "ran": False, "reason": f"unit types not verified on the backend: {cap['unverified_unit_types']}"}
    pk = packages or case["basis"]["packages"]; bad = [x for x in pk if x not in case["basis"]["packages"]]
    if bad: raise ValueError(f"packages {bad} are not listed in the case's basis.packages")
    known = ["base"] + [x["id"] for x in case.get("scenarios", [])]; sn = scenarios or known
    if [x for x in sn if x not in known]: raise ValueError(f"unknown scenarios {[x for x in sn if x not in known]}; known: {known}")
    out = []
    for scen in sn:
        sc_case = schema.apply_scenario(case, scen)
        for package in pk:
            fs = schema.to_flowsheet(sc_case, package); t = (transport_factory or default_transport)()
            try:
                be = DwsimBackend(t); hysys_writer.write(fs, be)
                solved = be.solve(); found = diagnose.classify(be.last_findings)
                if not solved: out.append({"scenario": scen, "package": package, "solved": False, "why": be.last_solve, "findings": found, "next_step": diagnose.next_step(found)}); continue
                cache, vals = {}, {}
                for r in sc_case["reported"]: vals[r["name"]] = compare_item(r, _simulated(r, fs, be, cache, sc_case["basis"].get("molar_mass_g_mol")), case["tolerance"]["pass_rel"])
                sim = {sid: cache.setdefault(sid, be.read_stream(sid)) for sid in fs.streams}
                out.append({"scenario": scen, "package": package, "solved": True, "values": vals, "spec_mismatches": be.check_solution(), "findings": found, "guardrails": guardrails.evaluate(sc_case, sim, scen)})
            finally:
                t.close()
    spread = {}                                                           # across packages, per scenario and reported value
    for scen in sn:
        sv = [o for o in out if o["scenario"] == scen and o["solved"]]
        if len(sv) > 1: spread[scen] = {r["name"]: (max(o["values"][r["name"]]["simulated"] for o in sv) - min(o["values"][r["name"]]["simulated"] for o in sv)) / abs(r["value"]) for r in schema.apply_scenario(case, scen)["reported"] if r.get("value")}
    solved = [o for o in out if o["solved"]]
    own = [o for o in solved if o["package"] == case["basis"]["package_in_paper"]]
    return {"case": case["id"], "case_hash": schema.case_hash(case), "ran": True, "results": out, "package_spread_rel": spread,
            "paper_package_within_tol": None if case["basis"]["package_in_paper"] not in case["basis"]["packages"] else         # None: the source does not say which package it used, so there is nothing to compare against
                                        bool(own) and len(own) == sum(o["package"] == case["basis"]["package_in_paper"] for o in out) and all(v["within_tol"] for o in own for v in o["values"].values()),
            "all_within_tol": bool(solved) and len(solved) == len(out) and all(v["within_tol"] for o in solved for v in o["values"].values()),
            "note": "within tolerance is not verification: a human reviews the case, the package spread and the scenario effects before status becomes verified"}


def reproduce(case: dict, run: dict) -> dict:
    """Do the base-scenario results match the numbers an earlier hand run recorded (case.reproduce)? Only the first reported value is compared."""
    rp = case["reproduce"]; name = case["reported"][0]["name"]; ok = 0
    for pkg, want in rp["expected"].items():
        o = next((x for x in run["results"] if x["scenario"] == "base" and x["package"] == pkg and x["solved"]), None)
        if o and abs(o["values"][name]["simulated"] / want - 1) <= rp["rel_tol"]: ok += 1
    return {"matched": ok, "of": len(rp["expected"]), "solved": sum(o["solved"] for o in run["results"]), "total": len(run["results"])}


def ledger_rows(run: dict) -> list[dict]:
    rows = []
    for o in run["results"]:
        row = {"case": run["case"], "case_hash": run["case_hash"], "backend": "dwsim-mcp", "scenario": o["scenario"], "package": o["package"], "solved": o["solved"],
               "findings": [f"{f['code']}:{f['severity']}:{f['object']}" for f in o["findings"]],
               "guardrails": [f"{g['rule']}:{g['status']}:{g['object']}" for g in o.get("guardrails", []) if g["status"] != "pass"]}
        row.update({"values": o["values"], "spec_mismatches": o["spec_mismatches"]} if o["solved"] else {"why": o["why"], "next_step": o["next_step"]})
        rows.append(row)
    return rows
