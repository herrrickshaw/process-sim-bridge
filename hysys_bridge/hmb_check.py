"""After solve: compare HYSYS-calculated values with the H&MB. Flags disagreement,
which catches wrong fluid package, bad units, and mis-transcribed numbers alike."""
from __future__ import annotations
from dataclasses import dataclass
from .ir import Flowsheet
from .backend import Backend

TOL = {"T": (0.5, 0.005), "P": (1.0, 0.01), "mass": (0.0, 0.01), "mol": (0.0, 0.01),
       "vol": (0.0, 0.03), "vf": (0.02, 0.0), "H": (0.0, 0.03)}     # (abs, rel)


@dataclass
class Diff:
    stream: str; prop: str; hmb: float; hysys: float | None; ok: bool


def check(fs: Flowsheet, be: Backend) -> list[Diff]:
    get = getattr(be, "get_calc", be.get)          # spreadsheet backend: compare the CALCULATED (OUT sheet) values
    get_comp = getattr(be, "get_comp_calc", be.get_comp)
    out = []
    for s in fs.streams.values():
        pairs = {"T": s.T_C, "P": s.P_kPa, "mass": s.mass_flow_kg_h, "mol": s.molar_flow_kmol_h,
                 "vol": s.vol_flow_m3_h, "vf": s.checks.get("vapour_fraction")}
        for p, ref in pairs.items():
            if ref is None: continue
            got = get(s.id, p)
            a, r = TOL[p]
            out.append(Diff(s.id, p, ref, got, got is not None and abs(got - ref) <= a + r * abs(ref)))
        if s.composition_basis == "mole":
            got = get_comp(s.id)
            for c, x in s.composition.items():
                g = got.get(c)
                out.append(Diff(s.id, f"x[{c}]", x, g, g is not None and abs(g - x) <= 0.002 + 0.01 * x))
    return out
