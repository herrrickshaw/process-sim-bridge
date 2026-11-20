"""Utility-system sizing tools for the simulator bridge: compressed air and nitrogen, cooling water, demineralised water, steam.
Design basis and open items: docs/UTILITIES_DESIGN.md.

Every number is either physics (CoolProp: Air, Nitrogen, Water; mass and energy balances) or an input of yours. Where a default stands in for
a design choice (isentropic efficiency, cycles of concentration, boiler blowdown, demin recovery ...) it is listed in the result under
`assumed_defaults` so it cannot pass as data. No standard or vendor figure is built in. Steam uses steam_link (condensing duty).
"""
from __future__ import annotations
import math


def _cp():
    try: import CoolProp.CoolProp as CP
    except ImportError as e: raise RuntimeError("CoolProp is required: pip install CoolProp") from e
    return CP


def _num(a, key, default=None, lo=None, hi=None, assumed=None):
    if key in a: v = float(a[key])
    elif default is not None:
        v = default
        if assumed is not None: assumed[key] = default
    else: raise ValueError(f"{key} is required")
    if lo is not None and v < lo or hi is not None and v > hi: raise ValueError(f"{key}={v} outside [{lo}, {hi}]")
    return v


def compress(gas, nm3_h, P_in_kPa, P_out_kPa, T_in_C=30.0, T_ic_C=35.0, eta_is=0.75, eta_mech=0.95, max_ratio=4.0, aftercool=True, ic_dp_frac=0.0):
    """Multistage intercooled compression of `gas` ('air'|'nitrogen'), flow in Nm3/h (0 C, 101.325 kPa). Real-gas isentropic stages from CoolProp.
    Returns shaft power, discharge states and the heat removed in the intercoolers/aftercooler."""
    CP = _cp(); fl = {"air": "Air", "nitrogen": "Nitrogen", "n2": "Nitrogen"}.get(gas.lower())
    if fl is None: raise ValueError("gas must be 'air' or 'nitrogen'")
    if not (0 < P_in_kPa < P_out_kPa): raise ValueError("need 0 < P_in_kPa < P_out_kPa")
    if not (0 < eta_is <= 1 and 0 < eta_mech <= 1): raise ValueError("efficiencies must be in (0, 1]")
    rho_n = CP.PropsSI("D", "T", 273.15, "P", 101325.0, fl); m = nm3_h * rho_n / 3600.0                 # kg/s
    n = max(1, math.ceil(math.log(P_out_kPa / P_in_kPa) / math.log(max_ratio) - 1e-12)); r = (P_out_kPa / P_in_kPa) ** (1 / n)
    rows, P, T, w_tot, q_tot = [], P_in_kPa, T_in_C, 0.0, 0.0
    for i in range(1, n + 1):
        h1 = CP.PropsSI("H", "P", P * 1e3, "T", T + 273.15, fl); s1 = CP.PropsSI("S", "P", P * 1e3, "T", T + 273.15, fl)
        P2 = P * r; hs = CP.PropsSI("H", "P", P2 * 1e3, "S", s1, fl); h2 = h1 + (hs - h1) / eta_is
        T2 = CP.PropsSI("T", "P", P2 * 1e3, "H", h2, fl) - 273.15; w = (h2 - h1) / 1e3                      # kJ/kg
        last = i == n; cool = (not last) or aftercool
        q = 0.0
        if cool:
            Pc = P2 * (1 - ic_dp_frac); hc = CP.PropsSI("H", "P", Pc * 1e3, "T", T_ic_C + 273.15, fl); q = (h2 - hc) / 1e3 * m   # kW
        rows.append({"stage": i, "P_in_kPa": P, "P_out_kPa": P2, "ratio": r, "T_in_C": T, "T_out_C": T2, "work_kJ_kg": w, "cooler_kW": q, "cooler": "after" if last and cool else ("inter" if cool else None)})
        w_tot += w * m; q_tot += q; P, T = (P2 * (1 - ic_dp_frac), T_ic_C) if cool else (P2, T2)
    shaft = w_tot / eta_mech
    return {"gas": fl, "mass_kg_s": m, "nm3_h": nm3_h, "stages": n, "stage_ratio": r, "gas_power_kW": w_tot, "shaft_power_kW": shaft,
            "specific_kWh_per_Nm3": shaft / nm3_h, "cooling_duty_kW": q_tot, "stage_rows": rows}


def t_compressed_gas(a):
    asm = {}
    purge = _num(a, "dryer_purge_fraction", 0.0, 0.0, 0.9)
    nm3 = _num(a, "nm3_h", lo=0.0)
    out = compress(a["gas"], nm3 / (1 - purge), _num(a, "P_in_kPa", lo=1.0), _num(a, "P_out_kPa"), _num(a, "T_in_C", 30.0, assumed=asm), _num(a, "T_ic_C", 35.0, assumed=asm),
                   _num(a, "eta_is", 0.75, 0.01, 1.0, asm), _num(a, "eta_mech", 0.95, 0.01, 1.0, asm), _num(a, "max_ratio", 4.0, 1.1, assumed=asm), bool(a.get("aftercool", True)),
                   _num(a, "ic_dp_frac", 0.0, 0.0, 0.2, asm))
    out.update({"delivered_nm3_h": nm3, "dryer_purge_fraction": purge, "compressed_nm3_h": nm3 / (1 - purge), "assumed_defaults": asm,
                "note": "air dryer purge (if any) is your input; nitrogen generation energy (PSA/membrane/cryogenic) is NOT included: compression of the supplied gas only"})
    return out


X_N2_AIR = 0.7808            # dry-air N2 mole fraction (CoolProp's Air mixture uses 0.7812; the difference is immaterial here)
R_GAS = 8.314462618
NM3_MOL = 101325.0 / (R_GAS * 273.15)


def min_separation_work(product_purity, n2_recovery, T_K=298.15):
    """Reversible (minimum) work to split air (N2 + 'other' = O2 and Ar lumped) into a product of N2 purity y (mole fraction) at N2 recovery R and a waste stream.
    Ideal-gas mixtures, isothermal, every stream at the same pressure: W = RT [sum_out n_k sum_i x_ik ln x_ik - sum_i x_i,air ln x_i,air] per mol of air.
    Returns (J per mol of air, J per Nm3 of product, product mol per mol air)."""
    y, R = product_purity, n2_recovery
    if not (X_N2_AIR < y <= 1.0): raise ValueError(f"product purity must exceed air's N2 fraction ({X_N2_AIR}) and be <= 1")
    if not (0 < R <= 1): raise ValueError("N2 recovery must be in (0, 1]")
    n_p = X_N2_AIR * R / y; n_w = 1 - n_p
    oth_w = (1 - X_N2_AIR) - n_p * (1 - y); n2_w = X_N2_AIR * (1 - R)
    def ent(n_a, n_b):                                    # n * sum x ln x for a two-component stream
        t = n_a + n_b
        return 0.0 if t <= 1e-15 else sum(n * math.log(n / t) for n in (n_a, n_b) if n > 1e-15)
    w = R_GAS * T_K * (ent(n_p * y, n_p * (1 - y)) + ent(n2_w, max(oth_w, 0.0)) - ent(X_N2_AIR, 1 - X_N2_AIR))
    return w, w / n_p * NM3_MOL, n_p


def t_n2_generation(a):
    """Electricity for on-site nitrogen. PSA/membrane: feed air compressed to feed_P_kPa, product leaves at feed_P less a drop and is boosted to the header;
    feed air = N2 product x purity / (recovery x 0.7808). Cryogenic: reversible work / second-law efficiency (an assumption), product compressed from product_P_kPa.
    Every route also reports the reversible minimum so the implied second-law efficiency of the figure you get is visible."""
    asm = {}; m = str(a.get("method", "")).lower()
    if m not in ("psa", "membrane", "cryogenic"): raise ValueError("method must be psa, membrane or cryogenic")
    nm3 = _num(a, "product_nm3_h", lo=0.0); y = _num(a, "purity", lo=0.8, hi=1.0); P_out = _num(a, "delivery_P_kPa", lo=101.325); T0 = _num(a, "ambient_T_C", 25.0, assumed=asm)
    eta_mech = _num(a, "eta_mech", 0.95, 0.01, 1.0, asm); eta_is = _num(a, "eta_is", 0.75, 0.01, 1.0, asm)
    if m == "cryogenic": R = _num(a, "n2_recovery", 0.95, 0.05, 1.0, asm)
    else: R = _num(a, "n2_recovery", lo=0.05, hi=1.0)                         # PSA/membrane recovery falls as purity rises and is vendor data: not defaulted
    w_min_mol, w_min_nm3, n_p = min_separation_work(y, R, T0 + 273.15)
    w_min_kwh_nm3 = w_min_nm3 / 3.6e6
    feed_air = nm3 * y / (R * X_N2_AIR); out = {"method": m, "product_nm3_h": nm3, "purity": y, "n2_recovery": R, "feed_air_nm3_h": feed_air, "waste_nm3_h": feed_air - nm3,
                                                "min_work_kWh_per_Nm3_product": w_min_kwh_nm3, "min_work_kW": w_min_kwh_nm3 * nm3, "cooling_duty_kW": 0.0, "stages": []}
    if m in ("psa", "membrane"):
        P_feed = _num(a, "feed_P_kPa", lo=150.0); dp = _num(a, "product_dp_kPa", 50.0, 0.0, assumed=asm)
        c1 = compress("air", feed_air, 101.325, P_feed, T_in_C=T0, eta_is=eta_is, eta_mech=eta_mech, aftercool=True)
        P_prod = P_feed - dp; kw = c1["shaft_power_kW"]; q = c1["cooling_duty_kW"]; out["stages"].append({"what": "feed air compression", **{k: c1[k] for k in ("shaft_power_kW", "cooling_duty_kW", "stages")}})
        if P_out > P_prod:
            c2 = compress("nitrogen", nm3, P_prod, P_out, T_in_C=T0, eta_is=eta_is, eta_mech=eta_mech, aftercool=True); kw += c2["shaft_power_kW"]; q += c2["cooling_duty_kW"]
            out["stages"].append({"what": "product booster", **{k: c2[k] for k in ("shaft_power_kW", "cooling_duty_kW", "stages")}})
        out.update({"product_P_kPa_from_unit": P_prod, "electric_kW": kw, "cooling_duty_kW": q, "note": "air dryer/purification duty, vacuum regeneration and membrane module pressure drop are not included; recovery is your input (vendor data)"})
    else:
        eta2 = _num(a, "second_law_eff", 0.25, 0.02, 1.0, asm); P_prod = _num(a, "product_P_kPa", 101.325, 101.325, assumed=asm)
        kw = w_min_kwh_nm3 * nm3 / eta2; q = 0.0
        if P_out > P_prod:
            c2 = compress("nitrogen", nm3, P_prod, P_out, T_in_C=T0, eta_is=eta_is, eta_mech=eta_mech, aftercool=True); kw += c2["shaft_power_kW"]; q = c2["cooling_duty_kW"]
            out["stages"].append({"what": "product compression", **{k: c2[k] for k in ("shaft_power_kW", "cooling_duty_kW", "stages")}})
        out.update({"second_law_eff": eta2, "product_P_kPa_from_unit": P_prod, "electric_kW": kw, "cooling_duty_kW": q,
                    "note": "second-law efficiency is an ASSUMPTION covering the whole cycle (air compression, purification, heat exchange, column); liquid-nitrogen backup and vaporiser are not included"})
    out["specific_kWh_per_Nm3"] = out["electric_kW"] / nm3
    out["implied_second_law_eff"] = out["min_work_kW"] / out["electric_kW"] if out["electric_kW"] else None      # on TOTAL electricity, product compression included
    out["assumed_defaults"] = asm
    return out


def t_cooling_water(a):
    CP = _cp(); asm = {}
    kw = _num(a, "duty_kW", lo=0.0); Ts, Tr = _num(a, "supply_T_C", 30.0, assumed=asm), _num(a, "return_T_C", 40.0, assumed=asm)
    if Tr <= Ts: raise ValueError("return_T_C must exceed supply_T_C")
    cpw = CP.PropsSI("C", "T", (Ts + Tr) / 2 + 273.15, "P", 3e5, "Water") / 1e3; kg_s = kw / (cpw * (Tr - Ts))
    rho = CP.PropsSI("D", "T", (Ts + Tr) / 2 + 273.15, "P", 3e5, "Water")
    out = {"duty_kW": kw, "supply_T_C": Ts, "return_T_C": Tr, "cp_kJ_kgK": cpw, "flow_kg_s": kg_s, "flow_m3_h": kg_s * 3600 / rho}
    if a.get("cooling_tower"):
        evap_frac = _num(a, "evaporative_fraction", 0.75, 0.0, 1.0, asm); coc = _num(a, "cycles_of_concentration", 4.0, 1.5, assumed=asm); drift = _num(a, "drift_fraction", 1e-5, 0.0, assumed=asm)
        hfg = (CP.PropsSI("H", "T", Tr + 273.15 - 5, "Q", 1, "Water") - CP.PropsSI("H", "T", Tr + 273.15 - 5, "Q", 0, "Water")) / 1e3
        evap = evap_frac * kw / hfg; drift_kg_s = drift * kg_s
        blow = max(evap / (coc - 1) - drift_kg_s, 0.0)               # salt balance: makeup*C0 = (blowdown + drift)*COC*C0, makeup = evap + blowdown + drift
        mk = evap + blow + drift_kg_s
        out.update({"evaporation_kg_s": evap, "blowdown_kg_s": blow, "drift_kg_s": drift_kg_s, "makeup_kg_s": mk, "makeup_m3_h": mk * 3600 / 1000.0, "latent_heat_kJ_kg": hfg})
    out["assumed_defaults"] = asm; return out


def t_demin_water(a):
    asm = {}
    steam = _num(a, "steam_kg_h", lo=0.0); ret = _num(a, "condensate_return_fraction", lo=0.0, hi=1.0)
    boiler = _num(a, "boiler_steam_kg_h", steam, 0.0, assumed=asm); bd = _num(a, "blowdown_pct", 1.0, 0.0, 50.0, asm); rec = _num(a, "demin_recovery", 0.85, 0.1, 1.0, asm)
    lost = steam * (1 - ret); blow = boiler * bd / 100.0; mk = lost + blow
    return {"steam_kg_h": steam, "condensate_return_fraction": ret, "condensate_lost_kg_h": lost, "boiler_blowdown_kg_h": blow, "demin_makeup_kg_h": mk,
            "demin_makeup_m3_h": mk / 1000.0, "demin_recovery": rec, "raw_water_to_demin_kg_h": mk / rec, "demin_reject_kg_h": mk / rec - mk, "assumed_defaults": asm,
            "note": "blowdown % applies to boiler_steam_kg_h (the whole boiler, not just this process steam); blowdown flash recovery and deaerator vent losses are not modelled"}


def t_balance(a):
    """One consistent utility balance for a plant demand: steam (condensing duty), compressed air, nitrogen, cooling water, demin make-up, electricity."""
    from . import steam_link as SL
    res = {}; asm = {}; elec = 0.0; cw_duty = _num(a, "other_cooling_duty_kW", 0.0, 0.0)
    if "steam_duty_kW" in a:
        st = SL.t_demand({"duty_kW": a["steam_duty_kW"], "steam_P_kPa": a["steam_P_kPa"], **({"condensate_T_C": a["condensate_T_C"]} if "condensate_T_C" in a else {})})
        res["steam"] = st
        res["demin"] = t_demin_water({"steam_kg_h": st["steam_kg_h"], "condensate_return_fraction": _num(a, "condensate_return_fraction", lo=0.0, hi=1.0),
                                      **{k: a[k] for k in ("blowdown_pct", "demin_recovery", "boiler_steam_kg_h") if k in a}})
    for key, gas in (("air_nm3_h", "air"), ("n2_nm3_h", "nitrogen")):
        if key in a and gas == "nitrogen" and "n2_method" in a:
            hdr = a.get("n2_P_out_kPa")
            if hdr is None: raise ValueError("n2_P_out_kPa (header pressure, kPa abs) is required with n2_nm3_h")
            sub = {dst: a[src] for src, dst in (("n2_purity", "purity"), ("n2_recovery", "n2_recovery"), ("n2_feed_P_kPa", "feed_P_kPa"), ("n2_second_law_eff", "second_law_eff")) if src in a}
            r = t_n2_generation({**sub, "method": a["n2_method"], "product_nm3_h": a[key], "delivery_P_kPa": hdr})
            res["nitrogen"] = {**r, "shaft_power_kW": r["electric_kW"]}; elec += r["electric_kW"]; cw_duty += r["cooling_duty_kW"]; continue
        if key in a:
            hdr = a[("air" if gas == "air" else "n2") + "_P_out_kPa"] if (("air" if gas == "air" else "n2") + "_P_out_kPa") in a else None
            if hdr is None: raise ValueError(f"{'air' if gas == 'air' else 'n2'}_P_out_kPa (header pressure, kPa abs) is required with {key}")
            r = t_compressed_gas({"gas": gas, "nm3_h": a[key], "P_in_kPa": a.get("suction_P_kPa", 101.325), "P_out_kPa": hdr,
                                  **({"dryer_purge_fraction": a["air_dryer_purge_fraction"]} if gas == "air" and "air_dryer_purge_fraction" in a else {})})
            res[gas] = r; elec += r["shaft_power_kW"]; cw_duty += r["cooling_duty_kW"]
    if cw_duty > 0:
        cw = t_cooling_water({"duty_kW": cw_duty, "cooling_tower": True, **{k: a[k] for k in ("supply_T_C", "return_T_C", "cycles_of_concentration") if k in a}}); res["cooling_water"] = cw
    res["summary"] = {"steam_kg_h": res.get("steam", {}).get("steam_kg_h"), "demin_makeup_kg_h": res.get("demin", {}).get("demin_makeup_kg_h"), "compressor_shaft_kW": elec,
                      "cooling_duty_kW": cw_duty, "cooling_water_m3_h": res.get("cooling_water", {}).get("flow_m3_h"), "cooling_tower_makeup_m3_h": res.get("cooling_water", {}).get("makeup_m3_h"),
                      "interconnections": ["compressor inter/aftercooler duty is added to the cooling-water duty", "steam condensate not returned becomes demin make-up",
                                           "no feedback is modelled between these loads and the steam cycle (see steam_lost_power)"]}
    return res


def _s(props, req): return {"type": "object", "properties": props, "required": req, "additionalProperties": False}
_n = {"type": "number"}

TOOLS = {
    "utility_nitrogen_generation": (t_n2_generation, "Electricity and cooling for on-site nitrogen by psa, membrane or cryogenic route: feed air (PSA/membrane) or reversible work over a second-law efficiency (cryogenic), product booster, and the reversible minimum with the implied second-law efficiency. PSA/membrane need your recovery (vendor data); cryogenic defaults (recovery 0.95, second-law efficiency 0.25) are assumptions listed in the result.",
                                    _s({"method": {"type": "string"}, "product_nm3_h": _n, "purity": _n, "delivery_P_kPa": _n, "n2_recovery": _n, "feed_P_kPa": _n, "product_dp_kPa": _n, "second_law_eff": _n,
                                        "product_P_kPa": _n, "ambient_T_C": _n, "eta_is": _n, "eta_mech": _n}, ["method", "product_nm3_h", "purity", "delivery_P_kPa"])),
    "utility_compressed_gas": (t_compressed_gas, "Size multistage intercooled compression of plant/instrument air or nitrogen (flow in Nm3/h, suction and header pressure kPa abs): shaft kW, stage temperatures, cooler duty. CoolProp real-gas stages; efficiencies are assumed defaults listed in the result; N2 generation energy not included.",
                               _s({"gas": {"type": "string"}, "nm3_h": _n, "P_in_kPa": _n, "P_out_kPa": _n, "T_in_C": _n, "T_ic_C": _n, "eta_is": _n, "eta_mech": _n, "max_ratio": _n, "aftercool": {"type": "boolean"}, "ic_dp_frac": _n, "dryer_purge_fraction": _n},
                                  ["gas", "nm3_h", "P_in_kPa", "P_out_kPa"])),
    "utility_cooling_water": (t_cooling_water, "Cooling-water flow for a duty and temperature rise; with cooling_tower=true also evaporation, blowdown, drift and make-up from cycles of concentration. Defaults (30->40 C, 75% evaporative, 4 cycles) are assumptions listed in the result.",
                              _s({"duty_kW": _n, "supply_T_C": _n, "return_T_C": _n, "cooling_tower": {"type": "boolean"}, "evaporative_fraction": _n, "cycles_of_concentration": _n, "drift_fraction": _n}, ["duty_kW"])),
    "utility_demin_water": (t_demin_water, "Demineralised-water make-up for a steam system: condensate not returned plus boiler blowdown, and the raw water the demin plant needs at a given recovery. Blowdown % and recovery are assumed defaults listed in the result.",
                            _s({"steam_kg_h": _n, "condensate_return_fraction": _n, "boiler_steam_kg_h": _n, "blowdown_pct": _n, "demin_recovery": _n}, ["steam_kg_h", "condensate_return_fraction"])),
    "utilities_balance": (t_balance, "One consistent utility balance: steam for a heat duty (condensing at steam_P_kPa), its demin make-up, compressed air and nitrogen to header pressures, and the cooling water for compressor coolers plus other duties incl. tower make-up. Returns each system and a summary of steam, make-up, electricity and cooling.",
                          _s({"steam_duty_kW": _n, "steam_P_kPa": _n, "condensate_T_C": _n, "condensate_return_fraction": _n, "blowdown_pct": _n, "demin_recovery": _n, "boiler_steam_kg_h": _n,
                              "air_nm3_h": _n, "air_P_out_kPa": _n, "air_dryer_purge_fraction": _n, "n2_nm3_h": _n, "n2_P_out_kPa": _n, "suction_P_kPa": _n,
                              "n2_method": {"type": "string"}, "n2_purity": _n, "n2_recovery": _n, "n2_feed_P_kPa": _n, "n2_second_law_eff": _n,
                              "other_cooling_duty_kW": _n, "supply_T_C": _n, "return_T_C": _n, "cycles_of_concentration": _n}, [])),
}
