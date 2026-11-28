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
W_COND_LB_H = 3_304_179                                                      # Exhibit 4-26 condensate flow, as in examples/doe_netl_b11a_steam_cycle.py
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


def fwh_cascade(line, heaters_kPa, m_c, h_in, ttd_K, P_main_kPa=3000.0):
    """Closed feedwater heaters with drains cascaded backwards to the condenser.
    heaters_kPa: extraction pressures; m_c: condensate flow through the train (kg/s); h_in: enthalpy entering the first heater (kJ/kg).
    Heater i raises the stream to Tsat_i - ttd_K. Heaters whose outlet is below the entering enthalpy do nothing (bypassed); the one straddling it
    does a partial duty. Extraction flows come from each heater's energy balance, top heater first (its drain heat is handed down).
    Returns (total power forgone kW, rows). Power forgone by heater i = e_i * (work that steam would still have done, from `line`)."""
    CP = _cp(); hs = sorted(heaters_kPa); rows = []
    t_out = [CP.PropsSI("T", "P", p * 1e3, "Q", 1, "Water") - 273.15 - ttd_K for p in hs]
    if any(b <= a for a, b in zip(t_out, t_out[1:])): raise ValueError("heater outlet temperatures must increase with pressure; check fwh_heaters and fwh_ttd_K")
    h_out = [steam_enthalpy_kj_kg(P_main_kPa, t) for t in t_out]
    prev = h_in
    for i, (P, ho) in enumerate(zip(hs, h_out)):
        duty = m_c * max(ho - max(prev, h_in), 0.0) if ho > h_in else 0.0
        prev = max(ho, prev)
        h_s, _, w, _, _, _ = line(P); h_f = steam_enthalpy_kj_kg(P, x=0.0)
        rows.append({"P_kPa": P, "T_sat_C": t_out[i] + ttd_K, "T_out_C": t_out[i], "duty_kW": duty, "h_steam": h_s, "h_drain": h_f, "work_kJ_kg": w})
    D, D_hf = 0.0, 0.0
    for r in reversed(rows):                                  # top heater first
        denom = r["h_steam"] - r["h_drain"]
        if denom <= 0: raise ValueError(f"heater at {r['P_kPa']:g} kPa: steam has no heat above its drain (wet-steam state)")
        e = (r["duty_kW"] - D * (D_hf - r["h_drain"])) / denom      # heat balance: e*(h_s-h_f) + D*(h_f,above - h_f) = duty
        r["extraction_kg_s"] = max(e, 0.0)
        if e < -1e-9: r["warning"] = "drain from above carries more heat than this heater needs; extraction clipped to 0 (energy balance not closed here)"
        D += r["extraction_kg_s"]; D_hf = r["h_drain"]
        r["drain_in_kg_s"] = D - r["extraction_kg_s"]
    return sum(r["extraction_kg_s"] * r["work_kJ_kg"] for r in rows), rows


def t_lost_power(a):
    """Power lost when steam is taken from the turbine at extraction_P_kPa instead of expanding to the condenser.
    Without reheat: start -> extraction (eta_s_to_extraction) -> condenser (eta_s_remaining). The extracted steam gives its heat in the
    process and returns as condensate, so what is lost is the work it would still have done.
    With reheat (reheat_P_kPa = cold-reheat pressure, reheat_T_C = hot-reheat temperature, both required together): HP section start ->
    cold reheat (eta_s_hp), reheater (pressure drop reheat_dp_frac, an assumption) , IP/LP section -> condenser (eta_s_ip_lp). Steam taken at or above the
    cold-reheat pressure also forgoes its reheat: lost power = remaining HP work + the whole IP/LP work; the boiler heat saved by skipping the
    reheater is reported separately (it is fuel, not power)."""
    CP = _cp()
    P0 = float(a.get("start_P_kPa", B11A_MS_P_PSIA * PSI_KPA)); T0 = float(a.get("start_T_C", (B11A_MS_T_F - 32) / 1.8))
    Pc = float(a.get("condenser_P_kPa", B11A_COND_P_PSIA * PSI_KPA)); Pe = float(a["extraction_P_kPa"])
    rh = "reheat_P_kPa" in a or "reheat_T_C" in a
    if rh and not ("reheat_P_kPa" in a and "reheat_T_C" in a): raise ValueError("reheat needs both reheat_P_kPa (cold reheat) and reheat_T_C (hot reheat); neither is guessed")
    if rh:
        e1 = e2 = None; ehp, eil = float(a.get("eta_s_hp", 0.88)), float(a.get("eta_s_ip_lp", 0.88))
        Pr, Trh, dpf = float(a["reheat_P_kPa"]), float(a["reheat_T_C"]), float(a.get("reheat_dp_frac", 0.10))
        Prh = Pr * (1 - dpf)
        if not (Pc < Prh < Pr < P0): raise ValueError(f"need condenser P < hot-reheat P ({Prh:.4g}) < cold-reheat P ({Pr:.4g}) < start P ({P0:.5g}) kPa")
        if not (Pc < Pe < P0): raise ValueError(f"extraction P must lie between condenser ({Pc:.3g}) and start ({P0:.5g}) kPa")
        if Prh < Pe < Pr: raise ValueError(f"extraction P is inside the reheater pressure drop ({Prh:.4g}-{Pr:.4g} kPa): no turbine stage is there")
        effs = (ehp, eil)
    else:
        e1, e2 = float(a.get("eta_s_to_extraction", 0.88)), float(a.get("eta_s_remaining", 0.88)); effs = (e1, e2)
        if not (Pc < Pe < P0): raise ValueError(f"need condenser P ({Pc:.3g}) < extraction P ({Pe:.4g}) < start P ({P0:.5g}) kPa")
    if not all(0 < e <= 1 for e in effs): raise ValueError("isentropic efficiencies must be in (0, 1]")
    h0 = CP.PropsSI("H", "P", P0 * 1e3, "T", T0 + 273.15, "Water") / 1e3
    reheat_info = None
    if rh:
        h_crh, w_hp, _ = expand(P0, h0, Pr, ehp)
        h_hrh = CP.PropsSI("H", "P", Prh * 1e3, "T", Trh + 273.15, "Water") / 1e3
        h_exh_full, w_il, q_exh_full = expand(Prh, h_hrh, Pc, eil)
        reheat_info = {"cold_reheat": {"P_kPa": Pr, "h_kJ_kg": h_crh}, "hot_reheat": {"P_kPa": Prh, "T_C": Trh, "h_kJ_kg": h_hrh}, "reheater_heat_kJ_kg": h_hrh - h_crh,
                       "hp_work_kJ_kg": w_hp, "ip_lp_work_kJ_kg": w_il}

    def line(P):
        """Steam taken at pressure P: (h there, quality there, work it would still do, exhaust h, exhaust quality, reheater heat skipped kJ/kg)."""
        if not rh:
            h, _, q = expand(P0, h0, P, e1); h_x, w, qx = expand(P, h, Pc, e2); return h, q, w, h_x, qx, 0.0
        if P >= Pr:                                           # HP section / cold reheat: forgoes the reheat too
            h, _, q = expand(P0, h0, P, ehp); h_after, w_hp_rest, _ = expand(P, h, Pr, ehp)
            return h, q, w_hp_rest + w_il, h_exh_full, q_exh_full, h_hrh - h_after
        h, _, q = expand(Prh, h_hrh, P, eil); h_x, w, qx = expand(P, h, Pc, eil); return h, q, w, h_x, qx, 0.0

    h_ext, q_ext, w_rest, h_exh, q_exh, reheat_skipped = line(Pe)
    if rh and Pe >= Pr: reheat_info["cold_reheat_via_extraction_h_kJ_kg"] = h_hrh - reheat_skipped
    extra_heat_saved = reheat_skipped
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
    kg_s = kw / dh; gross_kw = kg_s * w_rest; credit_kw = 0.0; credit = None
    warn = []
    cr = [k for k in ("fwh_extraction_P_kPa", "condensate_return_T_C") if k in a]
    if "fwh_heaters" in a:
        if "fwh_extraction_P_kPa" in a: raise ValueError("give either fwh_heaters (cascade) or fwh_extraction_P_kPa (single heater), not both")
        if "condensate_return_T_C" not in a: raise ValueError("the cascade credit needs condensate_return_T_C")
        hs = [float(x) for x in a["fwh_heaters"]]
        if not hs: raise ValueError("fwh_heaters is empty")
        for Pf in hs:
            if not (Pc < Pf < P0) or (rh and Prh < Pf < Pr): raise ValueError(f"heater pressure {Pf:.4g} kPa must lie on a turbine stage between the condenser and the start state (and not inside the reheater drop)")
        f = float(a.get("condensate_return_fraction", 1.0)); T_ret = float(a["condensate_return_T_C"])
        if not (0 <= f <= 1): raise ValueError("condensate_return_fraction must be in [0, 1]")
        P_ret, T_hw = float(a.get("return_P_kPa", 500.0)), float(a.get("hotwell_T_C", (101.0 - 32) / 1.8))
        if T_ret >= CP.PropsSI("T", "P", P_ret * 1e3, "Q", 0, "Water") - 273.15 - 1e-9: raise ValueError(f"condensate_return_T_C {T_ret} is not liquid at return_P_kPa {P_ret:g}")
        m_c = float(a.get("fwh_condensate_kg_s", W_COND_LB_H * LB_KG / 3600)); ttd = float(a.get("fwh_ttd_K", 3.0))
        if ttd < 0: raise ValueError("fwh_ttd_K must be >= 0")
        m_r = f * kg_s
        if m_r >= m_c: raise ValueError("returned condensate exceeds the condensate flow through the heater train (fwh_condensate_kg_s)")
        h_hw = steam_enthalpy_kj_kg(P_ret, T_hw); h_ret = steam_enthalpy_kj_kg(P_ret, T_ret)
        if T_hw >= CP.PropsSI("T", "P", hs and sorted(hs)[0] * 1e3, "Q", 1, "Water") - 273.15 - ttd: raise ValueError("hotwell is not colder than the first heater's outlet; check fwh_heaters / fwh_ttd_K")
        w0, rows0 = fwh_cascade(line, hs, m_c, h_hw, ttd)
        h_mix = h_hw + (m_r / m_c) * (h_ret - h_hw)                     # return joins the condensate at the hotwell, then runs through the train
        w1, rows1 = fwh_cascade(line, hs, m_c, h_mix, ttd)
        credit_kw = w0 - w1
        credit = {"model": "closed heaters, drains cascaded backwards to the condenser", "fwh_condensate_kg_s": m_c, "ttd_K": ttd, "returned_kg_s": m_r,
                  "T_in_with_return_C": CP.PropsSI("T", "P", P_ret * 1e3, "H", h_mix * 1e3, "Water") - 273.15, "power_forgone_without_return_kW": w0, "power_forgone_with_return_kW": w1,
                  "credit_kW": credit_kw, "heaters_without_return": rows0, "heaters_with_return": rows1,
                  "note": "TTD 3 K, the return/hotwell join and heater pressures are assumptions or your inputs, not read from the report; condensate flow defaults to the report's 3,304,179 lb/h"}
        if credit_kw < 0: warn.append("negative credit: check inputs")
        cr = []
    if cr:
        if len(cr) == 1: raise ValueError("the feedwater credit needs both fwh_extraction_P_kPa and condensate_return_T_C; neither is guessed")
        Pf, T_ret = float(a["fwh_extraction_P_kPa"]), float(a["condensate_return_T_C"]); f = float(a.get("condensate_return_fraction", 1.0))
        P_ret, T_hw = float(a.get("return_P_kPa", 500.0)), float(a.get("hotwell_T_C", (101.0 - 32) / 1.8))      # hotwell 101 F from the B11A report
        if not (0 <= f <= 1): raise ValueError("condensate_return_fraction must be in [0, 1]")
        if not (Pc < Pf < P0) or (rh and Prh < Pf < Pr): raise ValueError(f"fwh_extraction_P_kPa {Pf:.4g} must lie on a turbine stage between the condenser and the start state (and not inside the reheater drop)")
        if T_ret >= CP.PropsSI("T", "P", P_ret * 1e3, "Q", 0, "Water") - 273.15 - 1e-9: raise ValueError(f"condensate_return_T_C {T_ret} is not liquid at return_P_kPa {P_ret:g}")
        h_ret = steam_enthalpy_kj_kg(P_ret, T_ret); h_hw = steam_enthalpy_kj_kg(P_ret, T_hw)
        q_save = f * (h_ret - h_hw)                                           # heat per kg extracted that the feedwater train no longer has to supply
        h_f, _, w_f, _, _, _ = line(Pf); h_fsat = steam_enthalpy_kj_kg(Pf, x=0.0); dh_f = h_f - h_fsat
        if dh_f <= 0: raise ValueError("feedwater-heater steam gives no heat above its saturated liquid (wet-steam state below saturation?)")
        credit_kw = kg_s * max(q_save, 0.0) / dh_f * w_f
        Tsat_f = CP.PropsSI("T", "P", Pf * 1e3, "Q", 1, "Water") - 273.15
        if T_ret > Tsat_f - 5: warn.append(f"returned condensate at {T_ret:g} C is within 5 K of the heater steam saturation {Tsat_f:.1f} C: that heater cannot absorb its heat; pick a higher-pressure heater")
        if q_save <= 0: warn.append("returned condensate is no hotter than the hotwell: no credit")
        credit = {"fwh_extraction_P_kPa": Pf, "heater_steam_h_kJ_kg": h_f, "heater_heat_per_kg_kJ_kg": dh_f, "heater_steam_work_kJ_kg": w_f, "condensate_return_T_C": T_ret,
                  "return_fraction": f, "hotwell_T_C": T_hw, "heat_returned_kJ_per_kg_extracted": q_save, "heater_steam_displaced_kg_s": kg_s * max(q_save, 0.0) / dh_f,
                  "credit_kW": credit_kw, "note": "equivalent-work method: returned condensate heat displaces heater extraction steam, which then keeps expanding; "
                                                  "which heater absorbs the heat is YOUR choice (fwh_extraction_P_kPa), not read from the report"}
    lost_kw = gross_kw - credit_kw
    if q_exh is not None and q_exh < 0.85: warn.append(f"exhaust quality {q_exh:.2f} < 0.85: heavy moisture, the constant-efficiency model is optimistic")
    if q_ext is not None: warn.append(f"extraction steam is wet (quality {q_ext:.2f}); check the expansion line")
    out = {"duty_kW": kw, "duty_source": src, "start": {"P_kPa": P0, "T_C": T0, "h_kJ_kg": h0}, "condenser_P_kPa": Pc,
           "extraction": {"P_kPa": Pe, "T_C": T_ext, "h_kJ_kg": h_ext, "quality": q_ext, "T_sat_C": Tsat, "section": ("HP/cold reheat" if rh and Pe >= Pr else "IP/LP") if rh else "single line"},
           "heat_given_kJ_kg": dh, "steam_kg_s": kg_s, "steam_kg_h": kg_s * 3600, "work_still_available_kJ_kg": w_rest, "gross_lost_power_kW": gross_kw,
           "feedwater_credit": credit, "lost_power_kW": lost_kw,
           "lost_power_MW": lost_kw / 1e3, "lost_power_per_heat_delivered": lost_kw / kw, "exhaust": {"h_kJ_kg": h_exh, "quality": q_exh},
           "eta_s": ({"hp": effs[0], "ip_lp": effs[1]} if rh else {"to_extraction": e1, "remaining": e2}), "warnings": warn,
           "basis": "constant isentropic efficiencies (0.88 default is an ASSUMPTION, not from the report); no feedwater-heating credit or condensate-return credit. "
                    "Defaults: B11A main steam (1050 F, 2415 psia) and 1 psia hotwell from the report."}
    if rh:
        out["reheat"] = {**reheat_info, "reheat_dp_frac": dpf, "reheater_heat_saved_kW": kg_s * extra_heat_saved,
                         "note": "reheat_dp_frac is an assumption; cold/hot reheat pressure and temperature are yours (not read from the report)"}
    return out


def _s(props, req): return {"type": "object", "properties": props, "required": req, "additionalProperties": False}

TOOLS = {
    "steam_lost_power": (t_lost_power, "Power lost when a heat duty (duty_kW, or a solved refinery session by name) is supplied by steam extracted from the turbine at extraction_P_kPa: "
                                       "expansion line from a start state (default B11A main steam) with isentropic efficiencies (default 0.88, an assumption) to the extraction and then the condenser pressure. "
                                       "Returns steam flow, lost MW and MW lost per MW of heat delivered. Optional reheat: give reheat_P_kPa (cold reheat) and reheat_T_C (hot reheat) together. Optional feedwater-heating credit: condensate_return_T_C plus either fwh_extraction_P_kPa (one heater) or fwh_heaters (list of heater pressures: cascade with drains cascaded back, TTD 3 K assumed). CoolProp.",
                         _s({"duty_kW": {"type": "number"}, "name": {"type": "string"}, "extraction_P_kPa": {"type": "number"}, "start_P_kPa": {"type": "number"},
                             "start_T_C": {"type": "number"}, "condenser_P_kPa": {"type": "number"}, "eta_s_to_extraction": {"type": "number"},
                             "eta_s_remaining": {"type": "number"}, "condensate_T_C": {"type": "number"}, "reheat_P_kPa": {"type": "number"}, "reheat_T_C": {"type": "number"},
                             "reheat_dp_frac": {"type": "number"}, "eta_s_hp": {"type": "number"}, "eta_s_ip_lp": {"type": "number"},
                             "fwh_extraction_P_kPa": {"type": "number"}, "condensate_return_T_C": {"type": "number"}, "condensate_return_fraction": {"type": "number"},
                             "return_P_kPa": {"type": "number"}, "hotwell_T_C": {"type": "number"},
                             "fwh_heaters": {"type": "array", "items": {"type": "number"}}, "fwh_condensate_kg_s": {"type": "number"}, "fwh_ttd_K": {"type": "number"}}, ["extraction_P_kPa"])),
"steam_demand_for_duty": (t_demand, "Steam flow needed to deliver a heat duty (duty_kW, or a solved refinery session by name) by condensing steam at steam_P_kPa (abs) "
                                             "to condensate_T_C, with its share of the NETL B11A main-steam flow and boiler heat. CoolProp steam properties; heat balance only.",
                                   _s({"duty_kW": {"type": "number"}, "name": {"type": "string"}, "steam_P_kPa": {"type": "number"}, "steam_T_C": {"type": "number"},
                                       "condensate_T_C": {"type": "number"}, "process_outlet_T_C": {"type": "number"}, "min_approach_K": {"type": "number"}}, ["steam_P_kPa"]))}
# Cross-check (2026-11-20): the 2415 psia/1050 F -> 1000 kPa -> 1 psia line at eta_s 0.88 gives h_ext 2831.01 kJ/kg and 661.82 kJ/kg of remaining
# work with CoolProp HEOS (IAPWS-95) vs 2831.08 and 661.88 with CoolProp's IF97 backend (IAPWS-IF97, as used by DWSIM): 0.01% apart.
