"""Pressure-level rules around MAWP (ASME VIII-1 / API 520 / API 521 conventions).

All pressures kPa GAUGE unless named *_abs. ATM = 101.325 kPa.
"""
from __future__ import annotations
from dataclasses import dataclass, field

ATM = 101.325
# Allowable accumulation as a fraction of MAWP (ASME VIII-1 UG-125/UG-134, API 520 Pt I / API 521)
OVERPRESSURE = {"single": 0.10, "multiple": 0.16, "fire_single_or_multiple": 0.21}
MAX_SET = {"single": 1.00, "multiple_first": 1.00, "multiple_supplemental": 1.05}


@dataclass
class Levels:
    mawp: float
    set_pressure: float
    scenario: str
    relieving_gauge: float
    relieving_abs: float
    accumulation_pct: float
    hydrotest_min: float
    warnings: list[str] = field(default_factory=list)


def levels(mawp: float, set_pressure: float | None = None, scenario: str = "single",
           operating: float | None = None, lsr: float = 1.0, supplemental: bool = False) -> Levels:
    """Relieving pressure from MAWP + set pressure + scenario.

    scenario: 'single' (10%), 'multiple' (16%), 'fire' (21%).
    lsr: lowest stress ratio (S_test_temp / S_design_temp) for the hydrotest factor.
    """
    sc = {"fire": "fire_single_or_multiple"}.get(scenario, scenario)
    if sc not in OVERPRESSURE: raise ValueError(f"scenario must be single|multiple|fire, got {scenario!r}")
    sp = mawp if set_pressure is None else set_pressure
    w: list[str] = []
    cap = MAX_SET["multiple_supplemental" if supplemental else "single"] * mawp
    if sp > cap + 1e-9:
        raise ValueError(f"set pressure {sp} exceeds {'105%' if supplemental else '100%'} of MAWP {mawp}")
    if supplemental and sc != "multiple": w.append("supplemental valve (105% MAWP) only applies to multiple-valve installations")
    if sp > mawp: w.append("set pressure above MAWP: allowed only for the supplemental valve of a multi-valve set")
    acc = OVERPRESSURE[sc]
    relieving = sp + acc * mawp if sp <= mawp or supplemental else sp * (1 + acc)
    # accumulation is expressed against MAWP; relieving pressure may not exceed MAWP*(1+acc)
    relieving = min(relieving, mawp * (1 + acc))
    if operating is not None:
        r = operating / sp
        if r > 0.90: w.append(f"operating/set = {r:.0%}: above ~90% risks valve chatter/leakage; consider pilot-operated")
        if operating > mawp: w.append("operating pressure exceeds MAWP")
    if sp < mawp * 0.99 and sc == "single":
        w.append("set pressure well below MAWP: relieving pressure uses set + 10% of MAWP; verify against the allowable accumulation")
    return Levels(mawp, sp, sc, relieving, relieving + ATM, acc * 100, 1.3 * mawp * lsr, w)


def blocked_in_thermal_flow_m3_h(duty_kw: float | None = None, beta_per_K: float = 0.00074,
                                 heat_kw: float = 0.0, sg: float = 1.0, cp_kj_kgK: float = 2.1) -> float:
    """Thermal expansion of blocked-in liquid (API 521): q = beta*H / (rho*cp) -> m3/s -> m3/h.
    heat_kw: heat input (solar/steam tracing). Returns volumetric rate to relieve, m3/h."""
    h = heat_kw if duty_kw is None else duty_kw
    rho = sg * 1000.0
    return beta_per_K * h / (rho * cp_kj_kgK) * 3600.0
