"""Pre-simulation checks. Returns Issues; any 'error' blocks the HYSYS write."""
from dataclasses import dataclass
from .ir import Flowsheet

T_BOUNDS = (-273.15, 2000.0)
P_BOUNDS = (0.0, 5e5)              # kPa abs


@dataclass
class Issue:
    level: str       # error | warn
    where: str
    msg: str

    def __str__(self): return f"[{self.level.upper()}] {self.where}: {self.msg}"


def validate(fs: Flowsheet, comp_tol=1e-3, mb_tol=0.01, hysys_names: set[str] | None = None) -> list[Issue]:
    out: list[Issue] = []
    E = lambda w, m: out.append(Issue("error", w, m))
    W = lambda w, m: out.append(Issue("warn", w, m))
    for sid, s in fs.streams.items():
        if s.T_C is not None and not T_BOUNDS[0] < s.T_C < T_BOUNDS[1]: E(sid, f"T={s.T_C} C out of bounds")
        if s.P_kPa is not None and not P_BOUNDS[0] < s.P_kPa < P_BOUNDS[1]: E(sid, f"P={s.P_kPa} kPa out of bounds")
        flows = [x for x in (s.mass_flow_kg_h, s.molar_flow_kmol_h, s.vol_flow_m3_h) if x is not None]
        if any(x < 0 for x in flows): E(sid, "negative flow")
        if s.kind == "feed":
            if s.T_C is None or s.P_kPa is None: E(sid, "feed missing T or P")
            if not flows: E(sid, "feed has no flow spec")
            if not s.composition: E(sid, "feed has no composition")
        if s.composition:
            tot = sum(s.composition.values())
            if abs(tot - 1.0) > comp_tol:
                (E if abs(tot - 1.0) > 0.02 else W)(sid, f"composition sums to {tot:.5f} (basis={s.composition_basis})")
            if any(v < 0 for v in s.composition.values()): E(sid, "negative fraction")
            unknown = set(s.composition) - set(fs.components)
            if unknown: E(sid, f"components not in list: {sorted(unknown)}")
            if hysys_names is not None:
                bad = sorted(set(s.composition) - hysys_names)
                if bad: E(sid, f"not in HYSYS component db (map them): {bad}")
        vf = s.checks.get("vapour_fraction")
        if vf is not None and not 0 <= vf <= 1: E(sid, f"vapour fraction {vf} outside 0..1")
        if sid not in fs.streams or (s.src and s.src not in fs.units) or (s.dst and s.dst not in fs.units):
            E(sid, "dangling src/dst")
    for uid, u in fs.units.items():
        if u.type == "unknown": E(uid, "unit type unresolved")
        if not u.inlets: W(uid, "no inlet")
        if not u.outlets: W(uid, "no outlet")
        if u.type in ("mixer", "heater", "cooler", "pump", "valve", "compressor"):
            ins = [fs.streams[i].mass_flow_kg_h for i in u.inlets]
            outs = [fs.streams[o].mass_flow_kg_h for o in u.outlets]
            if None not in ins + outs and ins and outs:
                a, b = sum(ins), sum(outs)
                if a and abs(a - b) / a > mb_tol:
                    E(uid, f"mass balance: in {a:.2f} vs out {b:.2f} kg/h ({(b-a)/a:+.2%})")
    names = [s.id for s in fs.streams.values()]
    if len(names) != len(set(names)): E("flowsheet", "duplicate stream ids")
    return out


def blocking(issues): return [i for i in issues if i.level == "error"]
