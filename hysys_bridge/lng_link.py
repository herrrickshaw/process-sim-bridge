"""Link to lng-cost (herrrickshaw/lng-cost, separate repo): parametric LNG value-chain cost estimate (liquefaction, shipping, regasification).
The package is located by the operator-set env var LNG_COST_PATH (the folder that contains the `lng_cost` package, normally the repo's `src`); a tool argument can never supply it.

The repository says its defaults are illustrative placeholders, not sourced benchmarks, at about Class 5 screening accuracy. So every result here lists which inputs were
defaults (`defaults_used`) and repeats that warning; nothing is hidden. An input name the package does not have is refused. lng_cost_from_stream sizes the liquefaction
capacity from a SOLVED simulator stream: the caller states that the stream is the LNG product and the on-stream fraction (no default).
"""
from __future__ import annotations
import dataclasses, importlib, os, sys

WARNING = "lng-cost defaults are illustrative placeholders, not sourced benchmarks; screening accuracy (roughly Class 5), not a bankable cost"
SECTIONS = {"liquefaction": "LiquefactionInputs", "shipping": "ShippingInputs", "regas": "RegasInputs"}


def _pkg():
    p = os.environ.get("LNG_COST_PATH")
    if not p: raise PermissionError("set LNG_COST_PATH to the folder that contains the lng_cost package (the repo's src folder)")
    if p not in sys.path: sys.path.insert(0, p)
    return importlib.import_module("lng_cost")


def _build(pkg, a):
    objs, used = {}, {}
    for sec, cls in SECTIONS.items():
        given = a.get(sec) or {}
        if not isinstance(given, dict): raise ValueError(f"{sec} must be an object of input values")
        C = getattr(pkg, cls); fields = {f.name for f in dataclasses.fields(C)}
        bad = sorted(set(given) - fields)
        if bad: raise ValueError(f"{sec}: unknown input(s) {bad}; the package has {sorted(fields)}")
        objs[sec] = C(**{k: (int(v) if k == "life_years" else float(v)) for k, v in given.items()}); used[sec] = sorted(fields - set(given))
    return objs, used


def _run(pkg, a, extra=None):
    objs, used = _build(pkg, a)
    e = pkg.estimate(objs["liquefaction"], objs["shipping"], objs["regas"])
    return {**{k: getattr(e, k) for k in ("feed_gas", "fob_price", "shipping", "regas", "delivered")}, "unit": "USD/MMBtu", "liquefaction_capex_usd": e.liquefaction_capex_usd,
            "inputs": e.detail, "defaults_used": used, "warning": WARNING, **(extra or {})}


def t_estimate(a): return _run(_pkg(), a)


def capacity_mtpa_from_stream(mass_kg_h: float, on_stream_fraction: float) -> float:
    if not mass_kg_h > 0: raise ValueError("the stream's solved mass flow must be positive")
    if not 0 < on_stream_fraction <= 1: raise ValueError("on_stream_fraction must be in (0, 1]")
    return mass_kg_h * 8760.0 * on_stream_fraction / 1e9


def t_from_stream(a):
    from .dwsim import tools as DT
    c = DT._case(a["name"])
    if not c["be"].last_solve.get("ok"): raise RuntimeError("solve first: the capacity comes from a solved stream")
    if "on_stream_fraction" not in a: raise ValueError("on_stream_fraction is required (no default)")
    if a.get("stream_is_lng_product") is not True: raise ValueError("set stream_is_lng_product=true to state that this stream is the LNG product; the check is yours, the solve does not prove it")
    r = c["be"].read_stream(a["stream"]); cap = capacity_mtpa_from_stream(r["mass"], float(a["on_stream_fraction"]))
    given = dict(a.get("liquefaction") or {})
    if "capacity_mtpa" in given: raise ValueError("liquefaction.capacity_mtpa is taken from the stream; remove it")
    b = {**a, "liquefaction": {**given, "capacity_mtpa": cap}}
    return _run(_pkg(), b, {"capacity_from_stream": {"stream": a["stream"], "mass_kg_h": r["mass"], "on_stream_fraction": float(a["on_stream_fraction"]), "capacity_mtpa": cap,
                                                    "basis": "solved mass flow x 8760 h x on-stream fraction; the nameplate is not inferred"}})


def _s(props, req): return {"type": "object", "properties": props, "required": req, "additionalProperties": False}
_sec = {"type": "object", "additionalProperties": {"type": "number"}}
TOOLS = {
    "lng_cost_estimate": (t_estimate, "Delivered LNG cost (USD/MMBtu) from the lng-cost package: liquefaction, shipping and regasification inputs as objects (field names of the package; unknown names refused). "
                                      "Lists the inputs left at the package's illustrative defaults and warns that they are placeholders. Needs LNG_COST_PATH set by the operator. Screening only.",
                          _s({"liquefaction": _sec, "shipping": _sec, "regas": _sec}, [])),
    "lng_cost_from_stream": (t_from_stream, "Same estimate with the liquefaction capacity taken from a solved stream of a DWSIM session (mass flow x 8760 h x on_stream_fraction); you state that the stream is the LNG product. Needs LNG_COST_PATH.",
                             _s({"name": {"type": "string"}, "stream": {"type": "string"}, "on_stream_fraction": {"type": "number"}, "stream_is_lng_product": {"type": "boolean"},
                                 "liquefaction": _sec, "shipping": _sec, "regas": _sec}, ["name", "stream", "on_stream_fraction", "stream_is_lng_product"])),
}
