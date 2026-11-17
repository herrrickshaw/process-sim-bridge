"""Control valve sizing, IEC 60534-2-1 (incompressible and compressible, turbulent, Fp=1 unless given).
Inputs: bar abs, K, kg/h, m3/h. Output Kv (m3/h @1 bar) and Cv (US) = 1.156*Kv.
Not covered: laminar/transitional flow (Fr), reducers beyond a supplied Fp, noise, two-phase."""
from __future__ import annotations
import math
from dataclasses import dataclass

CV_PER_KV = 1.1560
N8 = 94.8          # mass flow kg/h, P bar, T K  -> Kv


@dataclass
class CV:
    service: str
    kv: float
    cv: float
    choked: bool
    notes: list[str]
    rated_kv_recommended: float

    def __str__(self):
        s = (f"{self.service}: Kv = {self.kv:.3f} m3/h, Cv = {self.cv:.3f}  "
             f"{'[CHOKED]' if self.choked else '[not choked]'}  -> select rated Kv >= {self.rated_kv_recommended:.2f} "
             "(sized so the calc is ~80% of rated)")
        return s + "".join(f"\n  NOTE: {n}" for n in self.notes)


def _rec(kv): return kv / 0.80


def liquid(q_m3_h, p1_bar, p2_bar, sg, pv_bar, pc_bar, FL=0.9, fp=1.0) -> CV:
    dp = p1_bar - p2_bar
    if dp <= 0: raise ValueError("p1 must exceed p2")
    FF = 0.96 - 0.28 * math.sqrt(pv_bar / pc_bar)
    dp_choke = FL ** 2 * (p1_bar - FF * pv_bar)
    choked = dp >= dp_choke
    dp_eff = dp_choke if choked else dp
    kv = q_m3_h / fp * math.sqrt(sg / dp_eff)
    notes = []
    if choked: notes.append(f"choked/flashing-limited: dP {dp:.2f} bar >= {dp_choke:.2f} bar; expect cavitation/flashing damage - consider anti-cavitation trim or staged drop")
    elif p2_bar < pv_bar: notes.append("downstream pressure below vapour pressure: flashing")
    sigma = (p1_bar - pv_bar) / dp
    if sigma < 2.0 and not choked: notes.append(f"cavitation index sigma={sigma:.2f} < 2: incipient cavitation likely")
    return CV("liquid", kv, kv * CV_PER_KV, choked, notes, _rec(kv))


def gas(w_kg_h, p1_bar, p2_bar, T_K, mw, k, z=1.0, xT=0.7, fp=1.0) -> CV:
    x = (p1_bar - p2_bar) / p1_bar
    if x <= 0: raise ValueError("p1 must exceed p2")
    Fk = k / 1.4
    x_choke = Fk * xT
    choked = x >= x_choke
    xe = x_choke if choked else x
    Y = 1 - xe / (3 * Fk * xT)                     # = 2/3 when choked
    kv = w_kg_h / (N8 * fp * p1_bar * Y) * math.sqrt(T_K * z / (xe * mw))
    notes = []
    if choked: notes.append("choked flow: flow no longer rises with lower p2; noise check required")
    if x > 0.5 and not choked: notes.append(f"dP/P1 = {x:.2f}: high drop, check noise")
    return CV("gas", kv, kv * CV_PER_KV, choked, notes, _rec(kv))


def steam(w_kg_h, p1_bar, p2_bar, rho1_kg_m3, k=1.3, xT=0.7, fp=1.0) -> CV:
    """Vapour with known inlet density (e.g. from steam tables): Kv = W/(N6 Y sqrt(x P1 rho1)), N6=31.6 (bar, kg/m3)."""
    x = (p1_bar - p2_bar) / p1_bar
    if x <= 0: raise ValueError("p1 must exceed p2")
    Fk = k / 1.4; xc = Fk * xT; choked = x >= xc; xe = xc if choked else x
    Y = 1 - xe / (3 * Fk * xT)
    kv = w_kg_h / (31.6 * fp * Y * math.sqrt(xe * p1_bar * rho1_kg_m3))
    return CV("steam/vapour", kv, kv * CV_PER_KV, choked, ["choked flow" ] if choked else [], _rec(kv))
