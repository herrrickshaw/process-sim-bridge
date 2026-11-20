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
            "warnings": r.warnings, "basis": "screening correlations, not a rigorous simulation"}


def _s(props, req): return {"type": "object", "properties": props, "required": req, "additionalProperties": False}

TOOLS = {
    "refinery_crudes": (t_crudes, "List the crude assays in the refinery-design library (key, name, API, sulfur wt%, TAN). Needs REFINERY_DESIGN_PATH.", _s({}, [])),
    "refinery_run": (t_run, "Whole-refinery mass balance (CDU/VDU + optional FCC + delayed coker) for a crude slate {crude_key: volume_fraction} at throughput_bpd. "
                            "Returns product pools, mass closure, FCC warnings, Nelson complexity. Screening only. Needs REFINERY_DESIGN_PATH.",
                     _s({"slate": {"type": "object"}, "throughput_bpd": {"type": "number"}, "fcc": {"type": "boolean"}, "coker": {"type": "boolean"}}, ["slate", "throughput_bpd"])),
}
