"""Couple a refinery heater duty to the NETL Case B11A steam cycle (public-domain constants from examples/doe_netl_b11a_steam_cycle.py).

steam_demand_for_duty: how much steam, condensed from a chosen state to a chosen condensate temperature, delivers a heat duty, and what
share of the B11A main-steam flow and boiler heat input that is. Steam properties come from CoolProp (IAPWS-95, an independent
reference, needs `pip install CoolProp`); the cooler path was cross-checked against DWSIM's steam tables (see the module test notes).
Pure heat balance, no turbine model: it does NOT estimate lost power, which depends on where in the turbine the steam is taken.
The duty comes from `duty_kW` or from a solved refinery session (`name`, via refinery_session_duty).
"""
from __future__ import annotations

LB_KG = 0.45359237
BTU_LB_KJ_KG = 2.326
B11A_MAIN_STEAM_LB_H = 4_120_442            # Exhibit 4-26: boiler outlet 1050 F, 2415 psia, H 1494 Btu/lb
B11A_MS_T_F, B11A_MS_P_PSIA, B11A_COND_P_PSIA, PSI_KPA = 1050.0, 2415.0, 1.0, 6.894757   # Exhibit 4-26 boiler outlet; HOTWELL 1 psia
B11A_BFW_H, B11A_MS_H = 471.0, 1494.0       # Btu/lb
B11A_BOILER_MW = B11A_MAIN_STEAM_LB_H * (B11A_MS_H - B11A_BFW_H) * BTU_LB_KJ_KG * LB_KG / 3600 / 1e3   # kW -> MW; ~1,235 MW fluid heat


def _cp():
    try: import CoolProp.CoolProp as CP
    except ImportError as e: raise RuntimeError("CoolProp is required: pip install CoolProp") from e
    return CP


def steam_enthalpy_kj_kg(P_kPa: float, T_C: float | None = None, x: float | None = None) -> float:
    CP = _cp()
    if x is not None: return CP.PropsSI("H", "P", P_kPa * 1e3, "Q", x, "Water") / 1e3
    return CP.PropsSI("H", "P", P_kPa * 1e3, "T", T_C + 273.15, "Water") / 1e3


def t_demand(a):
    t_proc = None
    if "duty_kW" in a: kw, src = float(a["duty_kW"]), "duty_kW argument"
    elif "name" in a:
        from .refinery_link import t_duty
        d = t_duty({"name": a["name"]}); kw, src, t_proc = d["duty_kW"], f"refinery session {a['name']!r}", d["outlet"]["T"]
    else: raise ValueError("pass duty_kW or the name of a solved refinery session")
    if kw <= 0: raise ValueError("duty must be positive (steam gives heat; a cooling duty cannot be met by condensing steam)")
    P = float(a["steam_P_kPa"]); CP = _cp(); Tsat = CP.PropsSI("T", "P", P * 1e3, "Q", 1, "Water") - 273.15
    T_in = a.get("steam_T_C")
    if T_in is not None and T_in < Tsat - 1e-9: raise ValueError(f"steam_T_C {T_in} is below saturation {Tsat:.1f} C at {P} kPa: that is liquid, not steam")
    h_in = steam_enthalpy_kj_kg(P, T_in) if T_in is not None else steam_enthalpy_kj_kg(P, x=1.0)
    T_out = float(a.get("condensate_T_C", Tsat))
    if T_out > Tsat + 1e-9: raise ValueError("condensate_T_C cannot exceed the saturation temperature")
    h_out = steam_enthalpy_kj_kg(P, x=0.0) if abs(T_out - Tsat) < 1e-9 else steam_enthalpy_kj_kg(P, T_out)
    dh = h_in - h_out; kg_s = kw / dh
    main = B11A_MAIN_STEAM_LB_H * LB_KG
    t_proc = a.get("process_outlet_T_C", t_proc); approach = float(a.get("min_approach_K", 10.0)); warn = []
    if t_proc is not None and Tsat - t_proc < approach:
        warn.append(f"INFEASIBLE: condensing steam at {Tsat:.1f} C cannot heat the process to {t_proc:.1f} C with a {approach:g} K approach; raise steam_P_kPa")
    return {"feasible": not warn, "warnings": warn, "process_outlet_T_C": t_proc, "min_approach_K": approach, "duty_kW": kw, "duty_source": src, "steam_P_kPa": P, "T_sat_C": Tsat, "steam_in_state": f"{T_in} C" if T_in is not None else "saturated vapour",
            "condensate_T_C": T_out, "heat_given_kJ_kg": dh, "steam_kg_s": kg_s, "steam_kg_h": kg_s * 3600,
            "share_of_B11A_main_steam_pct": 100 * kg_s * 3600 / main, "B11A_main_steam_kg_h": main,
            "B11A_boiler_heat_MW": B11A_BOILER_MW, "share_of_B11A_boiler_heat_pct": 100 * kw / 1e3 / B11A_BOILER_MW,
            "basis": "heat balance only; no turbine model, so lost power is not estimated"}


def expand(P_in_kPa, h_in_kj_kg, P_out_kPa, eta_s):
    """Adiabatic expansion with isentropic efficiency: returns (h_out kJ/kg, specific work kJ/kg, exit vapour quality or None if superheated)."""
    CP = _cp(); s_in = CP.PropsSI("S", "P", P_in_kPa * 1e3, "H", h_in_kj_kg * 1e3, "Water")
    h_s = CP.PropsSI("H", "P", P_out_kPa * 1e3, "S", s_in, "Water") / 1e3
    h_out = h_in_kj_kg - eta_s * (h_in_kj_kg - h_s)
    q = CP.PropsSI("Q", "P", P_out_kPa * 1e3, "H", h_out * 1e3, "Water")
    return h_out, h_in_kj_kg - h_out, (q if 0 <= q <= 1 else None)


def t_lost_power(a):
    """Power lost when steam is taken from the turbine at extraction_P_kPa instead of expanding to the condenser.
    Expansion line: start state -> extraction pressure (eta_s_to_extraction) -> condenser pressure (eta_s_remaining). The extracted steam
    gives its heat in the process and returns as condensate, so what is lost is the work it would still have done: m*(h_ext - h_exhaust)."""
    CP = _cp()
    P0 = float(a.get("start_P_kPa", B11A_MS_P_PSIA * PSI_KPA)); T0 = float(a.get("start_T_C", (B11A_MS_T_F - 32) / 1.8))
    Pc = float(a.get("condenser_P_kPa", B11A_COND_P_PSIA * PSI_KPA)); Pe = float(a["extraction_P_kPa"])
    e1, e2 = float(a.get("eta_s_to_extraction", 0.88)), float(a.get("eta_s_remaining", 0.88))
    if not (Pc < Pe < P0): raise ValueError(f"need condenser P ({Pc:.3g}) < extraction P ({Pe:.4g}) < start P ({P0:.5g}) kPa")
    if not (0 < e1 <= 1 and 0 < e2 <= 1): raise ValueError("isentropic efficiencies must be in (0, 1]")
    h0 = CP.PropsSI("H", "P", P0 * 1e3, "T", T0 + 273.15, "Water") / 1e3
    h_ext, w_to_ext, q_ext = expand(P0, h0, Pe, e1)
    h_exh, w_rest, q_exh = expand(Pe, h_ext, Pc, e2)
    T_ext = CP.PropsSI("T", "P", Pe * 1e3, "H", h_ext * 1e3, "Water") - 273.15
    kw, src = (float(a["duty_kW"]), "duty_kW argument") if "duty_kW" in a else (None, None)
    if kw is None and "name" in a:
        from .refinery_link import t_duty
        kw, src = t_duty({"name": a["name"]})["duty_kW"], f"refinery session {a['name']!r}"
    if kw is None: raise ValueError("pass duty_kW or the name of a solved refinery session")
    Tsat = CP.PropsSI("T", "P", Pe * 1e3, "Q", 1, "Water") - 273.15
    T_cond = float(a.get("condensate_T_C", Tsat))
    h_cond = steam_enthalpy_kj_kg(Pe, x=0.0) if abs(T_cond - Tsat) < 1e-9 else steam_enthalpy_kj_kg(Pe, T_cond)
    dh = h_ext - h_cond
    if dh <= 0: raise ValueError("extracted steam carries no heat above the condensate state (wet steam below the condensate enthalpy?)")
    kg_s = kw / dh; lost_kw = kg_s * w_rest
    warn = []
    if q_exh is not None and q_exh < 0.85: warn.append(f"exhaust quality {q_exh:.2f} < 0.85: heavy moisture, the constant-efficiency model is optimistic")
    if q_ext is not None: warn.append(f"extraction steam is wet (quality {q_ext:.2f}); check the expansion line and consider reheat (start_T_C/start_P_kPa)")
    return {"duty_kW": kw, "duty_source": src, "start": {"P_kPa": P0, "T_C": T0, "h_kJ_kg": h0}, "condenser_P_kPa": Pc,
            "extraction": {"P_kPa": Pe, "T_C": T_ext, "h_kJ_kg": h_ext, "quality": q_ext, "T_sat_C": Tsat}, "heat_given_kJ_kg": dh,
            "steam_kg_s": kg_s, "steam_kg_h": kg_s * 3600, "work_still_available_kJ_kg": w_rest, "lost_power_kW": lost_kw, "lost_power_MW": lost_kw / 1e3,
            "lost_power_per_heat_delivered": lost_kw / kw, "exhaust": {"h_kJ_kg": h_exh, "quality": q_exh},
            "eta_s": {"to_extraction": e1, "remaining": e2}, "warnings": warn,
            "basis": "single expansion line with constant isentropic efficiency; no reheat, feedwater heating or condensate-return credit unless the start state/duty encode them. "
                     "Defaults: B11A main steam (1050 F, 2415 psia) and 1 psia hotwell from the report; efficiencies 0.88 are an ASSUMPTION, not from the report."}


def _s(props, req): return {"type": "object", "properties": props, "required": req, "additionalProperties": False}

TOOLS = {
    "steam_lost_power": (t_lost_power, "Power lost when a heat duty (duty_kW, or a solved refinery session by name) is supplied by steam extracted from the turbine at extraction_P_kPa: "
                                       "expansion line from a start state (default B11A main steam) with isentropic efficiencies (default 0.88, an assumption) to the extraction and then the condenser pressure. "
                                       "Returns steam flow, lost MW and MW lost per MW of heat delivered. CoolProp; no reheat unless you give the start state.",
                         _s({"duty_kW": {"type": "number"}, "name": {"type": "string"}, "extraction_P_kPa": {"type": "number"}, "start_P_kPa": {"type": "number"},
                             "start_T_C": {"type": "number"}, "condenser_P_kPa": {"type": "number"}, "eta_s_to_extraction": {"type": "number"},
                             "eta_s_remaining": {"type": "number"}, "condensate_T_C": {"type": "number"}}, ["extraction_P_kPa"])),
"steam_demand_for_duty": (t_demand, "Steam flow needed to deliver a heat duty (duty_kW, or a solved refinery session by name) by condensing steam at steam_P_kPa (abs) "
                                             "to condensate_T_C, with its share of the NETL B11A main-steam flow and boiler heat. CoolProp steam properties; heat balance only.",
                                   _s({"duty_kW": {"type": "number"}, "name": {"type": "string"}, "steam_P_kPa": {"type": "number"}, "steam_T_C": {"type": "number"},
                                       "condensate_T_C": {"type": "number"}, "process_outlet_T_C": {"type": "number"}, "min_approach_K": {"type": "number"}}, ["steam_P_kPa"]))}
# Cross-check (2026-11-20): the 2415 psia/1050 F -> 1000 kPa -> 1 psia line at eta_s 0.88 gives h_ext 2831.01 kJ/kg and 661.82 kJ/kg of remaining
# work with CoolProp HEOS (IAPWS-95) vs 2831.08 and 661.88 with CoolProp's IF97 backend (IAPWS-IF97, as used by DWSIM): 0.01% apart.
