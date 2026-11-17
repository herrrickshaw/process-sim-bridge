"""Relief / safety valve (RSV / PSV / PRV) sizing per API 520 Part I (conventional orifice method).

Internals follow the API 520 US-customary equations (explicit conversions at the boundary,
so constants are the published ones). Public inputs are SI: kPa, K, kg/h, m3/h.
Scope: gas/vapour (critical + subcritical), steam, liquid (with viscosity correction),
fire case (API 521). NOT covered: two-phase/flashing (use API 520 Annex C / Omega method),
noise, reaction forces, inlet/outlet line losses (check the 3% inlet rule separately).
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from .pressure import levels, ATM, Levels

LB_PER_KG, PSI_PER_KPA, IN2_TO_MM2 = 2.20462262, 0.145037738, 645.16
GPM_PER_M3H = 4.40286754

# API 526 standard effective orifice areas, in^2
ORIFICES = {"D": 0.110, "E": 0.196, "F": 0.307, "G": 0.503, "H": 0.785, "J": 1.287, "K": 1.838,
            "L": 2.853, "M": 3.60, "N": 4.34, "P": 6.38, "Q": 11.05, "R": 16.0, "T": 26.0}


@dataclass
class Result:
    service: str
    required_in2: float
    required_mm2: float
    orifice: str | None
    orifice_mm2: float | None
    levels: Levels
    detail: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def __str__(self):
        o = f"{self.orifice} ({self.orifice_mm2:.0f} mm2)" if self.orifice else "NONE - exceeds T; use multiple valves"
        lv = self.levels
        lines = [f"{self.service}: required area {self.required_mm2:.1f} mm2 ({self.required_in2:.3f} in2) -> orifice {o}",
                 f"  MAWP {lv.mawp:g} kPag | set {lv.set_pressure:g} | relieving {lv.relieving_gauge:.1f} kPag ({lv.accumulation_pct:g}% accumulation)"]
        lines += [f"  {k} = {v:.4g}" if isinstance(v, float) else f"  {k} = {v}" for k, v in self.detail.items()]
        lines += [f"  WARNING: {w}" for w in self.warnings + lv.warnings]
        return "\n".join(lines)


def pick_orifice(a_in2: float):
    for letter, a in ORIFICES.items():
        if a >= a_in2: return letter, a
    return None, None


def _finish(service, a_in2, lv, detail, warn):
    L, A = pick_orifice(a_in2)
    if L is None:
        n = math.ceil(a_in2 / ORIFICES["T"]); warn.append(f"needs {n} x T orifice (or larger non-API valve)")
    return Result(service, a_in2, a_in2 * IN2_TO_MM2, L, A * IN2_TO_MM2 if A else None, lv, detail, warn)


def gas_C(k: float) -> float:
    """Coefficient C (US units) for critical flow of gas/vapour."""
    return 520.0 * math.sqrt(k * (2.0 / (k + 1.0)) ** ((k + 1.0) / (k - 1.0)))


def critical_ratio(k: float) -> float:
    return (2.0 / (k + 1.0)) ** (k / (k - 1.0))


def size_gas(w_kg_h, T_K, mw, k, z, mawp, set_pressure=None, scenario="single", backpressure=0.0,
             kd=0.975, kb=1.0, kc=1.0, operating=None) -> Result:
    """Gas/vapour. backpressure kPag (superimposed+built-up at relieving). kb: back-pressure
    factor for BALANCED bellows valves (from manufacturer curve; 1.0 for conventional with BP<10%)."""
    lv = levels(mawp, set_pressure, scenario, operating)
    warn: list[str] = []
    P1 = lv.relieving_abs * PSI_PER_KPA                  # psia
    P2 = (backpressure + ATM) * PSI_PER_KPA
    W, T = w_kg_h * LB_PER_KG, T_K * 1.8
    r, rc = P2 / P1, critical_ratio(k)
    if r <= rc:
        A = W / (gas_C(k) * kd * P1 * kb * kc) * math.sqrt(T * z / mw)
        regime, extra = "critical", {"C": gas_C(k)}
    else:
        f2 = math.sqrt(k / (k - 1) * r ** (2 / k) * (1 - r ** ((k - 1) / k)) / (1 - r))
        A = W / (735.0 * f2 * kd * kc) * math.sqrt(T * z / (mw * P1 * (P1 - P2)))
        regime, extra = "subcritical", {"F2": f2}
        warn.append("subcritical flow: a balanced-bellows or pilot valve is usually needed; kb not applied (F2 covers it)")
    bp_pct = backpressure / lv.set_pressure * 100 if lv.set_pressure else 0
    if bp_pct > 10 and kb == 1.0:
        warn.append(f"back pressure {bp_pct:.0f}% of set > 10%: conventional valve not suitable; use balanced bellows with its kb")
    if z <= 0 or z > 1.2: warn.append(f"Z={z} looks unusual")
    return _finish("gas/vapour", A, lv, {"regime": regime, "P1_psia": P1, "P2/P1": r, "critical ratio": rc, **extra}, warn)


def steam_kn(p1_psia: float) -> float:
    if p1_psia <= 1500: return 1.0
    if p1_psia <= 3200: return (0.1906 * p1_psia - 1000) / (0.2292 * p1_psia - 1061)
    raise ValueError("steam Kn correlation only valid to 3200 psia")


def size_steam(w_kg_h, mawp, set_pressure=None, scenario="single", ksh=1.0, kd=0.975, kb=1.0, kc=1.0,
               operating=None) -> Result:
    """Dry saturated / superheated steam. ksh: superheat correction (API 520 table; 1.0 = saturated)."""
    lv = levels(mawp, set_pressure, scenario, operating)
    P1 = lv.relieving_abs * PSI_PER_KPA
    kn = steam_kn(P1)
    A = (w_kg_h * LB_PER_KG) / (51.5 * P1 * kd * kb * kc * kn * ksh)
    warn = [] if P1 >= 15 else ["relieving pressure below ~15 psia: equation outside range"]
    return _finish("steam", A, lv, {"P1_psia": P1, "Kn": kn, "Ksh": ksh}, warn)


def size_liquid(q_m3_h, sg, mawp, set_pressure=None, scenario="single", backpressure=0.0,
                viscosity_cP=1.0, kd=0.65, kw=1.0, kc=1.0, operating=None) -> Result:
    """Liquid. kd 0.65 (API 520 default for liquid). kw: back-pressure factor for balanced valves
    (1.0 conventional / pilot). Viscosity correction Kv iterated on Reynolds number."""
    lv = levels(mawp, set_pressure, scenario, operating)
    dP = (lv.relieving_gauge - backpressure) * PSI_PER_KPA      # psi (gauge basis, as API 520 liquid eq.)
    if dP <= 0: raise ValueError("backpressure >= relieving pressure")
    Q = q_m3_h * 4.40286754                                      # m3/h -> US gpm
    kv, A = 1.0, 0.0
    for _ in range(50):
        A_new = Q / (38.0 * kd * kw * kc * kv) * math.sqrt(sg / dP)
        re = Q * 2800.0 * sg / (viscosity_cP * math.sqrt(A_new))
        kv_new = 1.0 / (0.9935 + 2.878 / math.sqrt(re) + 342.75 / re ** 1.5)
        if abs(A_new - A) < 1e-9: break
        A, kv = A_new, kv_new
    warn = []
    if viscosity_cP > 100: warn.append("viscosity > 100 cP: confirm with manufacturer sizing")
    return _finish("liquid", A, lv, {"dP_psi": dP, "Kv": kv, "Re": re}, warn)


def fire_vapour_rate(wetted_area_m2: float, latent_kJ_kg: float, env_factor=1.0,
                     adequate_drainage_and_firefighting=True) -> dict:
    """API 521 pool-fire heat input and vapour generation for a wetted vessel.
    Q[kW] = 43.2*F*A^0.82 (prompt fire fighting+drainage) or 70.9*F*A^0.82 (otherwise)."""
    c = 43.2 if adequate_drainage_and_firefighting else 70.9
    if wetted_area_m2 > 260: raise ValueError("A>260 m2: API 521 notes the A^0.82 correlation is only valid for A < ~260 m2 wetted")
    q = c * env_factor * wetted_area_m2 ** 0.82
    return {"Q_kW": q, "W_kg_h": q / latent_kJ_kg * 3600.0}
