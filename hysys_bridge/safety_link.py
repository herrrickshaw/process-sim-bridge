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


def _module(name: str):
    p = os.environ.get("PROCESS_SAFETY_PATH")
    if not p: raise PermissionError("set PROCESS_SAFETY_PATH to the folder that contains the process_safety package")
    if p not in sys.path: sys.path.insert(0, p)
    return importlib.import_module("process_safety." + name)


def _toolkit(): return _module("relief")


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


def _num(a, k, positive=False):
    if k not in a: raise ValueError(f"{k} is required (a team input; no default is applied)")
    v = float(a[k])
    if positive and not v > 0: raise ValueError(f"{k} must be positive")
    return v


def t_lopa(a):
    """LOPA for one scenario, optionally tied to a HAZOP deviation. Every frequency and PFD is the team's; nothing is defaulted."""
    S = _module("sil")
    ipl = a.get("ipl_pfds")
    if not isinstance(ipl, list) or not all(isinstance(x, (int, float)) and 0 < x <= 1 for x in ipl): raise ValueError("ipl_pfds must be a list of numbers in (0, 1] (an empty list means no independent layer is credited)")
    r = S.lopa(_num(a, "initiating_freq_per_yr", True), [float(x) for x in ipl], _num(a, "tolerable_per_yr", True), float(a.get("conditional_modifiers", 1.0)))
    out = {"lopa": {"unmitigated_per_yr": r.unmitigated_per_yr, "mitigated_per_yr": r.mitigated_per_yr, "tolerable_per_yr": r.tolerable_per_yr, "required_sif_pfd": r.required_pfd,
                    "required_rrf": r.required_rrf, "sil_needed": r.sil_needed, "meets_target_without_sif": r.meets_target_without_sif},
           "inputs_are_the_teams": {"initiating_freq_per_yr": a["initiating_freq_per_yr"], "ipl_pfds": ipl, "tolerable_per_yr": a["tolerable_per_yr"], "conditional_modifiers": a.get("conditional_modifiers", 1.0)},
           "reference_only": {"generic_ipl_pfd_quoted_by_the_toolkit": dict(S.GENERIC_IPL_PFD), "note": "typical values quoted by the toolkit, not applied; replace with site data and demonstrate independence"}}
    if a.get("sif"):
        f = a["sif"]; pfd = S.pfd_avg(f["arch"], _num(f, "lambda_du_per_h", True), _num(f, "proof_test_h", True), float(f.get("beta", 0.0)))
        out["sif"] = {"arch": f["arch"], "pfd_avg": pfd, "sil_achieved": S.sil_for_pfd(pfd), "meets_required": pfd <= r.required_pfd if not r.meets_target_without_sif else None,
                      "not_checked": "architectural constraints, systematic capability, proof-test coverage (the toolkit does not implement them)"}
    if a.get("spec_id") or a.get("deviation_id"):
        from .casebook import tools as CT
        if not (a.get("spec_id") and a.get("deviation_id")): raise ValueError("give both spec_id and deviation_id to tie the LOPA to a HAZOP deviation")
        spec = CT.load_spec(a["spec_id"]); dev = next((d for n in spec["nodes"] for d in n["deviations"] if d["id"] == a["deviation_id"]), None)
        if dev is None: raise KeyError(f"deviation {a['deviation_id']!r} is not in study {a['spec_id']!r}")
        out["hazop_deviation"] = {"study": a["spec_id"], "deviation": a["deviation_id"], "parameter": dev["parameter"], "guide_word": dev["guide_word"], "note": "the link is a label; the frequencies are not derived from the study"}
    out["note"] = "screening arithmetic from the toolkit (CCPS LOPA, IEC 61508-6 simplified PFDavg); not a SIL verification"
    return out


def t_flare_radiation(a):
    """Radiation from flaring one stream of a solved DWSIM case. The lower heating value and the distances are the caller's; the mass flow comes from the solve."""
    from .dwsim import tools as DT
    c = DT._case(a["name"])
    if not c["be"].last_solve.get("ok"): raise RuntimeError("solve first: flare radiation uses solved results only")
    r = c["be"].read_stream(a["stream"]); F = _module("flare")
    M = mixture_molar_mass(r["mass_fractions"], a["molar_masses"]); lhv = _num(a, "lhv_MJ_kg", True)
    Q = F.heat_release_W(r["mass"] / 3600.0, lhv); frac = F.radiant_fraction(M)
    out = {"stream": a["stream"], "mass_kg_h": r["mass"], "molar_mass_kg_kmol": M, "lhv_MJ_kg": lhv, "heat_release_MW": Q / 1e6, "radiant_fraction": frac,
           "basis": "point-source model (API 521 method as coded in the toolkit); distances are from the flame centre"}
    if a.get("distance_m") is not None: out["radiation_kW_m2_at_distance"] = {"distance_m": float(a["distance_m"]), "kW_m2": F.radiation_kW_m2(Q, _num(a, "distance_m", True), frac, float(a.get("tau", 1.0)))}
    chk = F.radiation_checks(Q, frac, a.get("flame_length_m"), float(a.get("tau", 1.0))); out["safe_distance_m_by_level"] = chk["distance_m"]; out["warnings"] = chk["warnings"]
    out["note"] = "screening only; the toolkit says to verify the allowable levels against your API 521 edition"
    return out


def _s(props, req): return {"type": "object", "properties": props, "required": req, "additionalProperties": False}

TOOLS = {
    "safety_relief_gas": (t_relief_gas,
        "Size a gas relief valve (API 520-I via the process-safety toolkit) for the blocked-outlet case of one stream of a solved DWSIM case. "
        "Needs set_g_kpa, k, molar_masses (g/mol). Needs PROCESS_SAFETY_PATH set by the operator. Screening only.",
        _s({"name": {"type": "string"}, "stream": {"type": "string"}, "set_g_kpa": {"type": "number"}, "k": {"type": "number"},
            "molar_masses": {"type": "object"}, "case": {"type": "string"}, "back_pressure_kpa_abs": {"type": "number"}, "Z": {"type": "number"}},
           ["name", "stream", "set_g_kpa", "k", "molar_masses"])),
    "safety_lopa": (t_lopa,
        "LOPA for one scenario via the process-safety toolkit: initiating frequency, independent-layer PFDs and tolerable frequency are all the team's inputs (none defaulted); optional SIF architecture check and an optional label tying it to a HAZOP study deviation. Needs PROCESS_SAFETY_PATH set by the operator. Screening only, not a SIL verification.",
        _s({"initiating_freq_per_yr": {"type": "number"}, "ipl_pfds": {"type": "array", "items": {"type": "number"}}, "tolerable_per_yr": {"type": "number"}, "conditional_modifiers": {"type": "number"},
            "sif": _s({"arch": {"type": "string"}, "lambda_du_per_h": {"type": "number"}, "proof_test_h": {"type": "number"}, "beta": {"type": "number"}}, ["arch", "lambda_du_per_h", "proof_test_h"]),
            "spec_id": {"type": "string"}, "deviation_id": {"type": "string"}}, ["initiating_freq_per_yr", "ipl_pfds", "tolerable_per_yr"])),
    "safety_flare_radiation": (t_flare_radiation,
        "Flare radiation for one stream of a solved DWSIM case (solved mass flow; lower heating value, molar masses and distances supplied by the caller) via the process-safety toolkit: heat release, radiant fraction, radiation at a distance, safe distances. Needs PROCESS_SAFETY_PATH. Screening only.",
        _s({"name": {"type": "string"}, "stream": {"type": "string"}, "molar_masses": {"type": "object"}, "lhv_MJ_kg": {"type": "number"}, "distance_m": {"type": "number"}, "flame_length_m": {"type": "number"}, "tau": {"type": "number"}},
           ["name", "stream", "molar_masses", "lhv_MJ_kg"])),
}
