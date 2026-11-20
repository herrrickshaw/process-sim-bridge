"""Whole-refinery screening tools backed by refinery-design-opensource (MIT, separate repo; needs numpy).

refinery_crudes lists the assay library; refinery_run runs crude(s) -> CDU/VDU -> FCC + delayed coker -> product pools for a
slate at a throughput and returns the pool yields (wt% of crude), mass closure, FCC screening warnings and Nelson complexity.
Pure calculation: no files written, nothing sent anywhere. The library is located by the operator-set env var
REFINERY_DESIGN_PATH (the folder that contains the `refinery_design` package); a tool argument can never supply it.
These are screening correlations, not a rigorous simulation: use them to size a feed for a unit-level DWSIM/Aspen case, not to
replace one.
"""
from __future__ import annotations
import importlib, os, sys


def _lib():
    p = os.environ.get("REFINERY_DESIGN_PATH")
    if not p: raise PermissionError("set REFINERY_DESIGN_PATH to the folder that contains the refinery_design package")
    if p not in sys.path: sys.path.insert(0, p)
    return importlib.import_module("refinery_design.assay"), importlib.import_module("refinery_design.flowsheet")


def t_crudes(a):
    assay, _ = _lib()
    return {"crudes": [{"key": k, **{f: getattr(c, f) for f in ("name", "api", "sulfur_wt", "tan")}} for k in assay.available_crudes() for c in [assay.load_crude(k)]]}


def t_run(a):
    assay, fl = _lib()
    comps = a["slate"]
    if not isinstance(comps, dict) or not comps: raise ValueError("slate must be {crude_key: volume_fraction}, e.g. {\"azeri_btc\": 0.7, \"cold_lake_blend\": 0.3}")
    if any(v <= 0 for v in comps.values()): raise ValueError("slate fractions must be positive")
    feed = assay.Slate([(assay.load_crude(k), v) for k, v in comps.items()])      # unknown key -> KeyError listing the library
    cfg = fl.RefineryConfig(fcc=a.get("fcc", True), coker=a.get("coker", True))
    r = fl.refine(feed, float(a["throughput_bpd"]), cfg)
    return {"slate": r.slate_name, "throughput_bpd": r.throughput_bpd, "feed_kg_h": r.feed_kg_h, "config": {"fcc": cfg.fcc, "coker": cfg.coker},
            "pools_kg_h": r.pools_kg_h, "pools_wt_pct": r.pools_wt_pct(), "mass_closure": r.mass_closure,
            "light_product_yield_wt_pct": r.light_product_yield_wt_pct, "middle_distillate_yield_wt_pct": r.middle_distillate_yield_wt_pct,
            "black_oil_yield_wt_pct": r.black_oil_yield_wt_pct, "nelson_complexity": r.complexity(),
            "fcc_regen_temperature_C": r.fcc.regen_temperature_C if r.fcc else None, "fcc_conversion_wt_pct": r.fcc.conversion_wt_pct if r.fcc else None,
            "distillation_kg_h": {k: v.mass_kg_h for k, v in r.distillation.streams.items()},
            "fcc_yields_wt_pct": {k: float(v) for k, v in r.fcc.yields_wt_pct.items()} if r.fcc else None,
            "coker_kg_h": ({"coke": r.coker.coke_kg_h, "gas": r.coker.gas_kg_h, "naphtha": r.coker.naphtha_kg_h, "gas_oil": r.coker.gas_oil_kg_h} if r.coker else None),
            "warnings": r.warnings, "basis": "screening correlations, not a rigorous simulation"}


# ILLUSTRATIVE surrogate compounds (mass fractions) for the lumped pools: the refinery model carries cuts, not compounds, so any DWSIM
# case built from a pool is only as good as this choice. Returned with every result; pass `surrogate` to override.
SURROGATES = {"lpg": {"Propane": 0.4, "N-butane": 0.6},
              "gasoline_range": {"N-hexane": 0.4, "N-heptane": 0.35, "N-octane": 0.25},
              "middle_distillate": {"N-decane": 0.5, "N-dodecane": 0.5}}


def t_to_session(a):
    """Create a hysys_bridge session (feed -> heater) from one refinery pool; build and solve it with dwsim_build/dwsim_solve."""
    from .ir import Flowsheet, Stream, Unit
    from . import mcp_server as M
    pool = a["pool"]; surr = a.get("surrogate") or SURROGATES.get(pool)
    if not surr: raise ValueError(f"no surrogate for pool {pool!r}; known: {sorted(SURROGATES)}, or pass surrogate={{compound: mass_fraction}}")
    if abs(sum(surr.values()) - 1.0) > 1e-6: raise ValueError("surrogate mass fractions must sum to 1")
    res = t_run(a); kg_h = res["pools_kg_h"].get(pool)
    if not kg_h or kg_h <= 0: raise ValueError(f"pool {pool!r} is empty for this configuration; pools: {sorted(res['pools_kg_h'])}")
    if a["name"] in M.SESSIONS and not a.get("overwrite"): raise ValueError(f"session {a['name']!r} exists; pass overwrite=true")
    fs = Flowsheet(a["name"], a.get("package", "Peng-Robinson"), list(surr))
    fs.streams = {"FEED": Stream("FEED", "feed", None, "H1", T_C=a.get("feed_T_C", 40.0), P_kPa=a.get("feed_P_kPa", 500.0), mass_flow_kg_h=kg_h,
                                 composition=dict(surr), composition_basis="mass"),
                  "OUT": Stream("OUT", "product", "H1", None, T_C=a["heat_to_C"], P_kPa=a.get("feed_P_kPa", 500.0) - a.get("dp_kPa", 50.0))}
    fs.units = {"H1": Unit("H1", "heater")}; fs.relink(); M.SESSIONS[a["name"]] = fs
    return {"session": a["name"], "pool": pool, "pool_kg_h": kg_h, "slate": res["slate"], "surrogate_mass_fractions": surr,
            "surrogate_note": "illustrative compounds standing in for a lumped cut; override with `surrogate`", "next": "dwsim_build, then dwsim_solve"}


def t_duty(a):
    """Heater duty of a refinery session after dwsim_solve: m * (h_out - h_in) from DWSIM's own stream enthalpies (server has no unit-duty result)."""
    from .dwsim import tools as DT
    c = DT._case(a["name"]); be = c["be"]
    if not be.last_solve.get("ok"): raise RuntimeError("solve first: duty comes from solved stream enthalpies only")
    u = next((uid for uid, x in be.units.items() if x["type"] == "heater"), None)
    if not u: raise ValueError("session has no heater")
    i, o = be.read_stream(be.units[u]["inlets"][0]), be.read_stream(be.units[u]["outlets"][0])
    if i["h_kJ_kg"] is None or o["h_kJ_kg"] is None: raise RuntimeError("DWSIM returned no mixture enthalpy")
    kw = i["mass"] / 3600 * (o["h_kJ_kg"] - i["h_kJ_kg"])
    return {"unit": u, "duty_kW": kw, "duty_MW": kw / 1e3, "duty_kJ_h": kw * 3600, "specific_kJ_kg": o["h_kJ_kg"] - i["h_kJ_kg"],
            "inlet": {"T": i["T"], "h_kJ_kg": i["h_kJ_kg"], "vapor_fraction": i["vapor_fraction"]},
            "outlet": {"T": o["T"], "h_kJ_kg": o["h_kJ_kg"], "vapor_fraction": o["vapor_fraction"]},
            "backend": "DWSIM" if c["live"] else "mock",
            "note": "enthalpy basis is DWSIM's; the difference is meaningful, the absolute values are not. Surrogate compounds make this illustrative."}


def _s(props, req): return {"type": "object", "properties": props, "required": req, "additionalProperties": False}

TOOLS = {
    "refinery_crudes": (t_crudes, "List the crude assays in the refinery-design library (key, name, API, sulfur wt%, TAN). Needs REFINERY_DESIGN_PATH.", _s({}, [])),
    "refinery_run": (t_run, "Whole-refinery mass balance (CDU/VDU + optional FCC + delayed coker) for a crude slate {crude_key: volume_fraction} at throughput_bpd. "
                            "Returns product pools, mass closure, FCC warnings, Nelson complexity. Screening only. Needs REFINERY_DESIGN_PATH.",
                     _s({"slate": {"type": "object"}, "throughput_bpd": {"type": "number"}, "fcc": {"type": "boolean"}, "coker": {"type": "boolean"}}, ["slate", "throughput_bpd"])),
    "refinery_to_session": (t_to_session, "Run the refinery balance and create a hysys_bridge session (feed -> heater) from one product pool (lpg|gasoline_range|middle_distillate) using illustrative surrogate compounds. Then dwsim_build (confirm) and dwsim_solve. Needs REFINERY_DESIGN_PATH.",
                            _s({"name": {"type": "string"}, "slate": {"type": "object"}, "throughput_bpd": {"type": "number"}, "pool": {"type": "string"},
                                "heat_to_C": {"type": "number"}, "feed_T_C": {"type": "number"}, "feed_P_kPa": {"type": "number"}, "dp_kPa": {"type": "number"},
                                "surrogate": {"type": "object"}, "package": {"type": "string"}, "fcc": {"type": "boolean"}, "coker": {"type": "boolean"}, "overwrite": {"type": "boolean"}},
                               ["name", "slate", "throughput_bpd", "pool", "heat_to_C"])),
    "refinery_session_duty": (t_duty, "Heater duty of a solved refinery session, from DWSIM's inlet and outlet stream enthalpies. Needs dwsim_solve first.",
                              _s({"name": {"type": "string"}}, ["name"])),
}
