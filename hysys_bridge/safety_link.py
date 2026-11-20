"""Link from solved simulator streams to the process-safety-design-toolkit (MIT, dependency-free, separate repo).

safety_relief_gas takes a stream of a SOLVED DWSIM case (T, P, mass flow from the server, not from specs), the set pressure and the
heat-capacity ratio k, and sizes a gas relief valve with the toolkit's API 520-I `gas_area` for the blocked-outlet case (the
valve must pass the whole stream). Nothing is guessed: k and the set pressure must be given; the molar mass is computed from the
stream's mass fractions and molar_masses (g/mol) that the caller supplies. The toolkit is located by the operator-set env var
PROCESS_SAFETY_PATH (folder containing the `process_safety` package); a tool argument can never supply it.
Screening only: the toolkit notes that the API standard text was not read; confirm coefficients against your edition.
"""
from __future__ import annotations
import importlib, os, sys


def _toolkit():
    p = os.environ.get("PROCESS_SAFETY_PATH")
    if not p: raise PermissionError("set PROCESS_SAFETY_PATH to the folder that contains the process_safety package")
    if p not in sys.path: sys.path.insert(0, p)
    return importlib.import_module("process_safety.relief")


def mixture_molar_mass(mass_fractions: dict, molar_masses: dict) -> float:
    """kg/kmol from mass fractions: 1/M = sum(w_i / M_i). Refuses compounds with no supplied molar mass."""
    miss = [c for c, w in mass_fractions.items() if w > 0 and c not in molar_masses]
    if miss: raise ValueError(f"molar_masses missing for {miss}")
    tot = sum(w for w in mass_fractions.values() if w > 0)
    return tot / sum(w / molar_masses[c] for c, w in mass_fractions.items() if w > 0)


def t_relief_gas(a):
    from .dwsim import tools as DT
    c = DT._case(a["name"])
    if not c["be"].last_solve.get("ok"): raise RuntimeError("solve first: relief sizing uses solved results only")
    r = c["be"].read_stream(a["stream"])
    R = _toolkit()
    M = mixture_molar_mass(r["mass_fractions"], a["molar_masses"])
    p1 = R.relieving_pressure_kpa(a["set_g_kpa"], a.get("case", "single_non_fire"))
    p2 = a.get("back_pressure_kpa_abs", R.ATM)
    res = R.gas_area(r["mass"], r["T"] + 273.15, p1, p2, M, a["k"], Z=a.get("Z", 1.0), set_g_kpa=a["set_g_kpa"])
    notes = list(res.notes)
    if r["P"] - R.ATM > 0.9 * a["set_g_kpa"]: notes.append("stream operating pressure is above 90% of set pressure: leakage/simmer risk (API 520 guidance)")
    if r["T"] + 273.15 < 200: notes.append("relieving temperature below 200 K: check the ideal-gas assumption and materials")
    return {"stream": a["stream"], "basis": "blocked outlet: whole stream relieved, solved T and mass flow from DWSIM",
            "T_C": r["T"], "P_operating_kPa": r["P"], "mass_kg_h": r["mass"], "molar_mass_kg_kmol": M, "k": a["k"],
            "relieving_pressure_kPa_abs": p1, "required_area_mm2": res.required_area_mm2, "orifice": res.orifice,
            "n_valves": res.n_valves, "regime": res.regime, "notes": notes}


def _s(props, req): return {"type": "object", "properties": props, "required": req, "additionalProperties": False}

TOOLS = {
    "safety_relief_gas": (t_relief_gas,
        "Size a gas relief valve (API 520-I via the process-safety toolkit) for the blocked-outlet case of one stream of a solved DWSIM case. "
        "Needs set_g_kpa, k, molar_masses (g/mol). Needs PROCESS_SAFETY_PATH set by the operator. Screening only.",
        _s({"name": {"type": "string"}, "stream": {"type": "string"}, "set_g_kpa": {"type": "number"}, "k": {"type": "number"},
            "molar_masses": {"type": "object"}, "case": {"type": "string"}, "back_pressure_kpa_abs": {"type": "number"}, "Z": {"type": "number"}},
           ["name", "stream", "set_g_kpa", "k", "molar_masses"])),
}
