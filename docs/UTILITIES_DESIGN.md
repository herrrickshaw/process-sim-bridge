# Utilities section: nitrogen, air, demineralised water, cooling water, steam (design, 2026-11-20)

Scope: how the bridge represents plant utilities next to the process flowsheet, what is calculated today, and what is deliberately left to you.
Tools: `hysys_bridge/utilities_link.py` (air, nitrogen, cooling water, demin water, balance) and `hysys_bridge/steam_link.py` (steam demand, turbine lost power).
No standard, vendor curve or plant datasheet was read for this section: every number is physics (CoolProp, mass and energy balances) or your input, and every defensible-looking default is listed in the result's `assumed_defaults`.

## 1. Principle
Utilities are modelled as **consumers of the process**, not as simulated plants: the process simulators (DWSIM, HYSYS, Aspen) produce duties, flows and stream states; the utility tools turn those into utility loads and make-up flows. Three rules keep them honest:
1. A load is derived from a solved result or a stated input (a duty, a Nm3/h demand, a header pressure). Nothing is guessed silently.
2. Each system has one balance (energy or mass) that the tests re-sum independently.
3. Cross-system links are explicit: compressor coolers load the cooling water, lost steam condensate loads the demin plant, extracted steam costs turbine power.

## 2. System by system
| System | Demand comes from | Calculated | Not calculated (you decide) |
|---|---|---|---|
| **Steam** | a heater/reboiler duty, e.g. `refinery_session_duty`; header pressure | steam flow to condense at a chosen pressure (`steam_demand_for_duty`); feasibility vs the process temperature; turbine power forgone, with reheat and a feedwater-heater cascade (`steam_lost_power`) | header pressure levels, letdown/desuperheating, trap and flash losses, boiler efficiency and fuel |
| **Demin water** | steam not returned as condensate + boiler blowdown (`utility_demin_water`) | make-up, raw water to the demin plant at a given recovery, reject | resin/membrane design, regeneration chemicals, condensate polishing, deaerator vent loss, blowdown flash recovery |
| **Cooling water** | cooler, condenser and compressor-cooler duties (`utility_cooling_water`) | circulation flow from duty and temperature rise; with a tower: evaporation, blowdown, drift, make-up from cycles of concentration | tower thermal rating (approach to wet bulb), water treatment, pump head, fouling |
| **Plant / instrument air** | Nm3/h demand, header pressure, optional dryer purge (`utility_compressed_gas`) | multistage intercooled compression power, stage temperatures, cooler duty | dryer type and dew point, receiver sizing, filtration, distribution losses |
| **Nitrogen** | Nm3/h demand, purity, header pressure | `utility_nitrogen_generation`: PSA and membrane (feed air from your recovery, compression, booster), cryogenic (reversible work over a second-law efficiency); the reversible minimum and implied second-law efficiency are always shown; `utility_compressed_gas` compresses supplied nitrogen | PSA/membrane recovery (vendor data, required, no default), air purification/dryer duty, vacuum regeneration, liquid-N2 backup and vaporiser, blanketing and purge rates, vent recovery |
`utilities_balance` runs the pieces together for one plant demand and returns each system plus a summary (steam kg/h, demin make-up, compressor kW, cooling duty and water, tower make-up).

## 3. Balances used
- Steam: `m = Q / (h_in - h_condensate)`, CoolProp IAPWS-95; condensing at `steam_P_kPa` to `condensate_T_C` (default saturated liquid).
- Demin: `make-up = steam x (1 - return fraction) + boiler steam x blowdown%`; `raw water = make-up / recovery`.
- Cooling water: `m = Q / (cp dT)`; tower: `evaporation = evaporative fraction x Q / h_fg`, `makeup = evaporation + blowdown + drift`, and a salt balance `makeup = COC x (blowdown + drift)`, so `blowdown + drift = evaporation / (COC - 1)`.
- Nitrogen generation: reversible work from ideal-mixture unmixing (N2 vs lumped O2+Ar, isothermal): 0.0207 kWh per Nm3 of pure N2 at full recovery, checked against the closed form; PSA/membrane feed air = N2 product x purity / (recovery x 0.7808); cryogenic electricity = reversible work / second-law efficiency (assumed).
- Compression: `n = ceil(ln(Pout/Pin) / ln(max ratio))` equal-ratio stages, real-gas isentropic enthalpy rise per stage divided by an isentropic efficiency, cooled back to `T_ic` between stages (and after the last unless switched off); shaft = gas power / mechanical efficiency; cooler duty = enthalpy removed.

## 4. How the utilities meet the simulators
- **Steam and cooling water as process utilities**: a heater or cooler in DWSIM is specified by an outlet temperature; its duty (from stream enthalpies, `refinery_session_duty`) is the input to the utility tools. DWSIM does not model the steam header, so the link is one-way.
- **Nitrogen and air as process feeds**: purge, blanketing and stripping streams enter a flowsheet as ordinary feed streams (composition N2, or air); the utility tools size the supply of those same Nm3/h.
- **Feedback is not modelled**: extracting steam does not change the NETL B11A model's other flows; `steam_lost_power` reports the effect separately.

## 5. Verified vs assumed
- Verified: steam condensing path vs DWSIM steam tables (0.005%); expansion line vs CoolProp's IF97 backend (0.01%); demin and tower balances by closure tests; compression compared with the ideal-gas single-stage figure (intercooling saves, as it must, by 10-20% here); a two-stage 1000 Nm3/h air case at 8 bar abs gives about 0.106 kWh/Nm3 shaft with the assumed efficiencies.
- Assumed (defaults, listed in every result): isentropic efficiency 0.75 and mechanical 0.95; suction/intercooler temperatures 30/35 C; maximum stage ratio 4; cooling water 30 to 40 C; 75% of tower heat rejected by evaporation; 4 cycles of concentration; boiler blowdown 1%; demin recovery 85%.
- Not checked against any vendor or plant data. Treat results as screening-level.

## 6. Open items (in priority order)
1. Nitrogen: vendor recovery-versus-purity curves for PSA and membranes, liquid N2 vaporiser duty, and the cryogenic second-law efficiency (the 0.25 default is a placeholder).
2. Air dryer and dew-point design (purge fraction by dryer type is now only an input).
3. Header hydraulics and pressure levels, including steam letdown and desuperheating; relief of each header (the toolkit link `safety_relief_gas` can size gas headers).
4. Cooling-tower thermal rating against wet-bulb; closed-loop versus once-through cooling.
5. A boiler model so blowdown and fuel follow from steam demand, and a link back to the B11A cycle's other flows.
6. Plant availability and standby (N+1) sizing, which is a design-philosophy input, not a calculation.
