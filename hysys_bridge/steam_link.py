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


def _s(props, req): return {"type": "object", "properties": props, "required": req, "additionalProperties": False}

TOOLS = {"steam_demand_for_duty": (t_demand, "Steam flow needed to deliver a heat duty (duty_kW, or a solved refinery session by name) by condensing steam at steam_P_kPa (abs) "
                                             "to condensate_T_C, with its share of the NETL B11A main-steam flow and boiler heat. CoolProp steam properties; heat balance only.",
                                   _s({"duty_kW": {"type": "number"}, "name": {"type": "string"}, "steam_P_kPa": {"type": "number"}, "steam_T_C": {"type": "number"},
                                       "condensate_T_C": {"type": "number"}, "process_outlet_T_C": {"type": "number"}, "min_approach_K": {"type": "number"}}, ["steam_P_kPa"]))}
