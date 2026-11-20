"""Turn the simulator's diagnostic findings into the next step of a casebook loop. Codes and causes are from DWSIM's own documentation
(dwsim.org/tutorials: Common Mistakes, Degrees of Freedom, Recycles and Convergence, Diagnostic Codes), read 2026-11-20; see docs/DWSIM_ERRORS_AND_FIXES.md.
The point is to decide WHAT may be changed: a loop may fix the case record from its source or fix our own backend mapping, but may never change a number to make a
result come out right."""
from __future__ import annotations

CASE_ERROR = ("the case record or the flowsheet built from it is wrong: fix it from the source document, re-validate, re-run. Never change a published number to pass.",
              ["EMPTY_FLOWSHEET", "NO_COMPOUNDS", "NO_PROPERTY_PACKAGE", "DUPLICATE_TAG", "STREAM_DANGLING", "UNIT_UNCONNECTED", "UNIT_NO_FEED", "UNIT_NO_PRODUCT",
               "FEED_NO_PRESSURE", "FEED_NO_TEMPERATURE", "FEED_NO_FLOW", "FEED_NO_COMPOSITION", "FEED_COMPOSITION_NOT_NORMALISED", "VAPOR_FRACTION_OUT_OF_RANGE",
               "SPEC_MISSING", "SPLITTER_RATIOS_NOT_NORMALISED", "REACTOR_NO_REACTIONS"])
BACKEND = ("our backend wrote the specification the wrong way (calculation mode, units, percent versus fraction): fix the mapping in hysys_bridge/dwsim/backend.py, add a test, re-run every case.",
           ["EFFICIENCY_OUT_OF_RANGE", "UNIT_HAD_NO_EFFECT"])
PLAUSIBILITY = ("the solve finished but the result is not physical: record it as a warning in the ledger and compare with the source. If the source flowsheet shows the same thing it is a property of the case; if not, look for a basis or sign error first.",
                ["HEATER_COOLED", "COOLER_HEATED", "PRESSURE_WRONG_DIRECTION", "HX_TEMPERATURE_CROSS", "HX_HEAT_FLOW_REVERSED", "TEMPERATURE_BELOW_FREEZING",
                 "COLUMN_REFLUX_BELOW_MINIMUM", "MIXER_PRESSURE_MISMATCH"])
CONVERGENCE = ("a recycle loop needs a better starting point. Allowed levers, in this order, each logged: give the tear stream an estimate, solve the open loop first and use its stream, "
               "ramp the recycle fraction, then acceleration. Not allowed: loosening the tolerance until it passes.", ["RECYCLE_NO_ESTIMATE"])
CATEGORY = {c: (name, text) for name, (text, codes) in (("case_error", CASE_ERROR), ("backend_mapping", BACKEND), ("plausibility", PLAUSIBILITY), ("convergence", CONVERGENCE)) for c in codes}
UNKNOWN = ("unclassified code: read it with dwsim_explain_finding, then add it to this table with a test.")


def classify(findings: list[dict]) -> list[dict]:
    out = []
    for f in findings or []:
        cat, action = CATEGORY.get(f.get("code"), ("unclassified", UNKNOWN))
        out.append({"code": f.get("code"), "severity": f.get("severity"), "object": f.get("object"), "category": cat, "loop_action": action, "simulator_fix": f.get("fix")})
    return out


def next_step(classified: list[dict]) -> str | None:
    """The one thing to do next: the most severe, most fixable-by-us category first."""
    order = ["case_error", "backend_mapping", "convergence", "unclassified", "plausibility"]
    rank = lambda c: (c["severity"] != "blocker", order.index(c["category"]))
    return min(classified, key=rank)["loop_action"] if classified else None
