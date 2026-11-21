"""Draw a process flow diagram (refinery) and a utilities flow diagram from LIVE tool results, so every number on the page comes from a tool.

    REFINERY_DESIGN_PATH=~/.graphify/gh-clones/refinery-design-opensource \
    DWSIM_MCP_CMD="podman run -i --rm --network none ghcr.io/danwbr/dwsim-mcp:latest --stdio" \
    python3 -m examples.build_flow_diagrams            # needs numpy and CoolProp; writes docs/diagrams/

Case: 70% Azeri BTC + 30% Cold Lake Blend at 200,000 bpd; the gasoline-range pool is heated 40 -> 120 C by steam extracted at 1 MPa.
Illustrative inputs (marked on the diagram): surrogate compounds for the pool, 0.88 turbine efficiencies, PSA recovery 0.45, header pressures, demand figures.
Without DWSIM_MCP_CMD there is no heater duty, so the PFD omits the heater and the UFD says a solved DWSIM case is needed.
"""
import html, os, sys
from pathlib import Path
from hysys_bridge import mcp_server as M, refinery_link as RL, steam_link as SL, utilities_link as UL
from hysys_bridge.dwsim import tools as DT

OUT = Path(__file__).resolve().parent.parent / "docs" / "diagrams"
SLATE, BPD, POOL, T_OUT = {"azeri_btc": 0.7, "cold_lake_blend": 0.3}, 200_000, "gasoline_range", 120.0
STEAM_P, RETURN_FRAC, T_RET, HEATERS = 1000.0, 0.5, 90.0, [100.0, 200.0, 400.0, 800.0]
AIR_NM3, AIR_P, N2_NM3, N2_P, N2_RECOVERY, OTHER_COOL_KW = 2000.0, 800.0, 500.0, 800.0, 0.45, 5000.0

def f0(x): return f"{x:,.0f}"
def f1(x): return f"{x:,.1f}"
def f2(x): return f"{x:,.2f}"


def gather():
    d = {}
    d["ref"] = RL.t_run({"slate": SLATE, "throughput_bpd": BPD})
    d["duty_kW"] = None
    if os.environ.get("DWSIM_MCP_CMD"):
        M.SESSIONS.pop("pfd", None); DT.CASES.pop("pfd", None)
        RL.t_to_session({"name": "pfd", "slate": SLATE, "throughput_bpd": BPD, "pool": POOL, "heat_to_C": T_OUT})
        DT.t_build({"name": "pfd", "confirm": True, "live": True}); ok = DT.t_solve({"name": "pfd"})["solved"]
        if ok: d["duty_kW"] = RL.t_duty({"name": "pfd"})["duty_kW"]
        DT.t_close({"name": "pfd"})
    if d["duty_kW"] is not None:
        d["steam"] = SL.t_demand({"duty_kW": d["duty_kW"], "steam_P_kPa": STEAM_P, "process_outlet_T_C": T_OUT})
        d["lost"] = SL.t_lost_power({"duty_kW": d["duty_kW"], "extraction_P_kPa": STEAM_P, "condensate_return_T_C": T_RET, "condensate_return_fraction": RETURN_FRAC, "fwh_heaters": HEATERS})
        d["bal"] = UL.t_balance({"steam_duty_kW": d["duty_kW"], "steam_P_kPa": STEAM_P, "condensate_return_fraction": RETURN_FRAC, "air_nm3_h": AIR_NM3, "air_P_out_kPa": AIR_P,
                                 "n2_nm3_h": N2_NM3, "n2_P_out_kPa": N2_P, "n2_method": "psa", "n2_purity": 0.995, "n2_recovery": N2_RECOVERY, "n2_feed_P_kPa": N2_P,
                                 "other_cooling_duty_kW": OTHER_COOL_KW, "boiler_fuel": "methane"})
    return d


STYLE = """<style>
 .bg{fill:#fff}.box{fill:#f4f6f8;stroke:#5b6770;stroke-width:1.4}.unit{fill:#e6f0fb;stroke:#2563a8;stroke-width:1.6}.util{fill:#eaf6ee;stroke:#2f7d4f;stroke-width:1.6}
 .src{fill:#fdf1e3;stroke:#b4691f;stroke-width:1.6}.title{font:600 13px system-ui,sans-serif;fill:#14202b}.t{font:12px system-ui,sans-serif;fill:#14202b}.sm{font:11px system-ui,sans-serif;fill:#3b4a56}
 .h{font:700 17px system-ui,sans-serif;fill:#14202b}.note{font:11px system-ui,sans-serif;fill:#6b4a12}.ln{stroke:#33414c;stroke-width:1.6;fill:none}.st{stroke:#b4691f;stroke-width:2.2;fill:none}
 .cw{stroke:#2563a8;stroke-width:2.2;fill:none}.gas{stroke:#2f7d4f;stroke-width:2.2;fill:none}.dm{stroke:#7b3fa0;stroke-width:2.2;fill:none}.el{stroke:#a82525;stroke-width:2;fill:none;stroke-dasharray:6 4}
 @media (prefers-color-scheme:dark){.bg{fill:#14181c}.box{fill:#1f262d;stroke:#7a8894}.unit{fill:#1b2e44;stroke:#6aa6e8}.util{fill:#1a3025;stroke:#5fb784}.src{fill:#3a2a17;stroke:#e0a060}
 .title,.t,.h{fill:#e8edf1}.sm{fill:#b4c0ca}.note{fill:#e8c98a}.ln{stroke:#b4c0ca}.st{stroke:#e0a060}.cw{stroke:#6aa6e8}.gas{stroke:#5fb784}.dm{stroke:#c08ae0}.el{stroke:#e07070}}
</style><defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="context-stroke"/></marker></defs>"""


class Svg:
    def __init__(s, w, h, title): s.w, s.h, s.o = w, h, [f'<rect class="bg" width="{w}" height="{h}"/>', f'<text class="h" x="20" y="28">{html.escape(title)}</text>']
    def box(s, x, y, w, h, title, lines=(), cls="unit"):
        s.o.append(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/><text class="title" x="{x + 10}" y="{y + 20}">{html.escape(title)}</text>')
        for i, l in enumerate(lines): s.o.append(f'<text class="t" x="{x + 10}" y="{y + 38 + 15 * i}">{html.escape(l)}</text>')
    def arrow(s, pts, cls="ln", label="", lx=None, ly=None, sub=""):
        d = "M" + " L".join(f"{x} {y}" for x, y in pts)
        s.o.append(f'<path class="{cls}" d="{d}" marker-end="url(#a)"/>')
        if label: s.o.append(f'<text class="sm" x="{lx if lx is not None else pts[0][0] + 6}" y="{ly if ly is not None else pts[0][1] - 6}">{html.escape(label)}</text>')
        if sub: s.o.append(f'<text class="sm" x="{lx if lx is not None else pts[0][0] + 6}" y="{(ly if ly is not None else pts[0][1] - 6) + 13}">{html.escape(sub)}</text>')
    def text(s, x, y, t, cls="sm"): s.o.append(f'<text class="{cls}" x="{x}" y="{y}">{html.escape(t)}</text>')
    def render(s): return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {s.w} {s.h}" width="100%" role="img">{STYLE}{"".join(s.o)}</svg>'


def pfd(d):
    r = d["ref"]; D = r["distillation_kg_h"]; P = r["pools_kg_h"]; Y = r["fcc_yields_wt_pct"]; K = r["coker_kg_h"]; vgo, vr = D["vgo"], D["vacuum_residue"]
    fc = lambda k: vgo * Y[k] / 100
    S = Svg(1500, 700, "Process flow diagram: crude slate to product pools (kg/h)")
    S.box(20, 300, 190, 86, "Crude slate", [r["slate"][:30], f"{f0(BPD)} bpd", f"{f0(r['feed_kg_h'])} kg/h"], "src")
    S.box(260, 270, 150, 146, "CDU / VDU", ["cuts at 150 / 250 /", "370 / 550 C", f"mass closure {r['mass_closure']:.3f}"])
    S.arrow([(210, 343), (260, 343)])
    # pool column: row y of each pool box (box height 58); entry y = row + 29
    rows = {"lpg": 60, "gasoline_range": 140, "middle_distillate": 220, "fuel_gas": 300, "slurry": 380, "petcoke": 460, "fcc_coke_burned": 540}
    names = {"lpg": "LPG", "gasoline_range": "Gasoline range", "middle_distillate": "Middle distillate", "fuel_gas": "Fuel gas", "slurry": "FCC slurry", "petcoke": "Petcoke", "fcc_coke_burned": "FCC coke burned"}
    parts = {"lpg": f"crude {f0(D['lpg'])} + FCC {f0(fc('lpg'))}", "gasoline_range": f"naphtha {f0(D['naphtha'])} + FCC {f0(fc('gasoline'))} + coker {f0(K['naphtha'])}",
             "middle_distillate": f"kero+diesel {f0(D['kerosene'] + D['diesel'])} + LCO {f0(fc('lco'))} + coker {f0(K['gas_oil'])}", "fuel_gas": f"FCC {f0(fc('dry_gas'))} + coker {f0(K['gas'])}",
             "slurry": f"FCC {f0(fc('slurry'))}", "petcoke": f"coker {f0(K['coke'])}", "fcc_coke_burned": f"FCC {f0(fc('coke'))} (flue gas)"}
    for k, y in rows.items():
        S.box(1000, y, 270, 58, names[k], [f"{f0(P[k])} kg/h   {r['pools_wt_pct'][k]:.1f} wt%", parts[k]], "box")
    ey = {k: y + 29 for k, y in rows.items()}
    # CDU cuts: straight to the pool rows (grey), VGO and residue to the units
    def cut(n, v, y, tgt_y):
        S.arrow([(410, 343), (440, 343), (440, y), (470, y)], "ln"); S.text(476, y - 5, f"{n}  {f0(v)}", "t")
        if tgt_y is not None: S.arrow([(640, y), (1000, tgt_y)] if y == tgt_y else [(640, y), (660, y), (660, tgt_y), (1000, tgt_y)], "ln")
    cut("LPG", D["lpg"], ey["lpg"], ey["lpg"]); cut("Naphtha", D["naphtha"], ey["gasoline_range"], ey["gasoline_range"])
    cut("Kerosene", D["kerosene"], ey["middle_distillate"] - 8, ey["middle_distillate"] - 8); cut("Diesel", D["diesel"], ey["middle_distillate"] + 12, ey["middle_distillate"] + 12)
    S.arrow([(410, 343), (440, 343), (440, 420), (470, 420)], "ln"); S.text(476, 415, f"VGO  {f0(vgo)}", "t")
    S.arrow([(410, 343), (440, 343), (440, 520), (470, 520)], "ln"); S.text(476, 515, f"Vacuum residue  {f0(vr)}", "t")
    S.box(630, 372, 170, 96, "FCC (on VGO)", [f"conversion {r['fcc_conversion_wt_pct']:.0f}%", f"regen {r['fcc_regen_temperature_C']:.0f} C", f"{len(r['warnings'])} screening warning(s)"])
    S.box(630, 490, 170, 96, "Delayed coker", ["on vacuum residue", f"coke {f0(K['coke'])} kg/h"])
    S.arrow([(470, 420), (630, 420)], "ln"); S.arrow([(470, 520), (630, 520)], "ln")
    fcc_out = [("lpg", "lpg", 384), ("gasoline", "gasoline_range", 394), ("lco", "middle_distillate", 404), ("dry_gas", "fuel_gas", 414), ("slurry", "slurry", 424), ("coke", "fcc_coke_burned", 434)]
    for i, (yk, pool, y0) in enumerate(fcc_out):
        lane = 815 + 10 * i; ty = ey[pool] + (6 if pool == "middle_distillate" else 0)
        S.arrow([(800, y0), (lane, y0), (lane, ty), (1000, ty)], "st")
    cok_out = [("coke", "petcoke", 506), ("gas", "fuel_gas", 520), ("naphtha", "gasoline_range", 534), ("gas_oil", "middle_distillate", 548)]
    for i, (yk, pool, y0) in enumerate(cok_out):
        lane = 895 + 10 * i; ty = ey[pool] + (14 if pool == "middle_distillate" else 8 if pool in ("fuel_gas", "gasoline_range") else 0)
        S.arrow([(800, y0), (lane, y0), (lane, ty), (1000, ty)], "dm")
    S.text(815, 362, "FCC products", "sm"); S.text(895, 606, "coker products", "sm")
    S.text(20, 660, "Grey: CDU cuts to pools. Orange: FCC products. Purple: coker products. Pool boxes list where each pool's kg/h comes from. Source: refinery_run (refinery-design-opensource), screening correlations.", "note")
    if d["duty_kW"] is not None:
        S.box(1300, 125, 190, 110, "Pool heater H1", ["DWSIM, solved", f"40 -> {T_OUT:.0f} C", f"duty {f2(d['duty_kW'] / 1e3)} MW", f"steam {f0(d['steam']['steam_kg_h'])} kg/h at {STEAM_P / 1e3:g} MPa"], "util")
        S.arrow([(1270, ey["gasoline_range"]), (1300, ey["gasoline_range"])], "ln"); S.text(1300, 252, "surrogate hexane/heptane/octane", "sm")
        S.text(1300, 266, "stands in for the lumped pool", "sm")
    return S.render()


def ufd(d):
    S = Svg(1240, 700, "Utilities flow diagram: steam, demin water, cooling water, compressed air, nitrogen")
    if d["duty_kW"] is None:
        S.text(20, 80, "Needs a solved DWSIM case for the heater duty: set DWSIM_MCP_CMD and rerun.", "t"); return S.render()
    st, lo, b = d["steam"], d["lost"], d["bal"]; bo = b["boiler"]; dm, cw, air, n2, sm = b["demin"], b["cooling_water"], b["air"], b["nitrogen"], b["summary"]; cr = lo["feedwater_credit"]
    S.box(20, 70, 200, 90, "Boiler (B11A basis)", ["main steam 1050 F, 2415 psia", f"{f0(SL.B11A_MAIN_STEAM_LB_H * SL.LB_KG)} kg/h", f"{f0(SL.B11A_BOILER_MW)} MW fluid heat"], "src")
    S.box(300, 70, 250, 90, "Turbine", [f"extraction at {STEAM_P / 1e3:g} MPa", f"steam {f0(st['steam_kg_h'])} kg/h ({st['share_of_B11A_main_steam_pct']:.1f}% of main)", f"power lost {f2(lo['lost_power_MW'])} MW net"], "unit")
    S.box(610, 70, 200, 90, "Process heater H1", [f"duty {f2(d['duty_kW'] / 1e3)} MW", f"condenses at {st['T_sat_C']:.0f} C", f"-> {T_OUT:.0f} C gasoline pool"], "unit")
    S.arrow([(220, 115), (300, 115)], "st"); S.text(228, 104, "main steam", "sm")
    S.arrow([(550, 115), (610, 115)], "st"); S.text(551, 104, "extraction", "sm")
    S.box(610, 220, 200, 66, "Condensate", [f"{f0(st['steam_kg_h'] * RETURN_FRAC)} kg/h returned at {T_RET:.0f} C", f"{f0(dm['condensate_lost_kg_h'])} kg/h lost"], "box")
    S.arrow([(710, 160), (710, 220)], "st")
    S.box(300, 220, 250, 66, "Feedwater train", [f"{len(HEATERS)} heaters {HEATERS[0]:g}-{HEATERS[-1]:g} kPa (cascade)", f"return credit {f2(cr['credit_kW'] / 1e3)} MW"], "unit")
    S.arrow([(610, 253), (550, 253)], "dm"); S.text(560, 244, "return", "sm")
    S.arrow([(300, 253), (120, 253), (120, 160)], "st"); S.text(130, 245, "feedwater", "sm")
    S.box(20, 330, 260, 120, "Package boiler (alternative supply)", [f"same {f0(bo['steam_kg_h'])} kg/h at {STEAM_P / 1e3:g} MPa, methane", f"{f1(bo['heat_to_water_kW'] / 1e3)} MW to water, eff. {bo['efficiency_lhv'] * 100:.1f}% LHV", f"fuel {f0(bo['fuel_kg_h'])} kg/h, CO2 {f0(bo['co2_kg_h'])} kg/h",
                                                       f"stack {bo['stack_T_C']:.0f} C, {bo['combustion']['excess_air_pct']:.0f}% excess air (assumed)"], "src")
    S.box(610, 340, 200, 78, "Demin plant", [f"make-up {f0(dm['demin_makeup_kg_h'])} kg/h", f"raw water {f0(dm['raw_water_to_demin_kg_h'])} kg/h", f"reject {f0(dm['demin_reject_kg_h'])} kg/h"], "util")
    S.arrow([(610, 379), (425, 379), (425, 286)], "dm"); S.text(440, 372, "demin make-up", "sm")
    S.text(30, 466, "Boiler or B11A extraction: one supplies the steam, not both.", "sm")
    S.box(860, 70, 280, 100, "Cooling tower loop", [f"duty {f2(cw['duty_kW'] / 1e3)} MW ({cw['supply_T_C']:.0f}->{cw['return_T_C']:.0f} C)", f"circulation {f0(cw['flow_m3_h'])} m3/h", f"make-up {f1(cw['makeup_m3_h'])} m3/h, blowdown {f1(cw['blowdown_kg_s'] * 3.6)} m3/h"], "util")
    S.box(860, 220, 280, 66, "Coolers", [f"compressor coolers {f2((air['cooling_duty_kW'] + n2['cooling_duty_kW']) / 1e3)} MW", f"other process {f2(OTHER_COOL_KW / 1e3)} MW"], "unit")
    S.arrow([(930, 170), (930, 220)], "cw"); S.text(936, 200, "cold", "sm"); S.arrow([(1070, 220), (1070, 170)], "cw"); S.text(1076, 200, "hot", "sm")
    S.box(860, 340, 280, 96, "Plant / instrument air", [f"{f0(AIR_NM3)} Nm3/h to {AIR_P / 1e3:g} MPa abs", f"{air['stages']} stages, {f0(air['shaft_power_kW'])} kW", f"{f2(air['specific_kWh_per_Nm3'])} kWh/Nm3"], "unit")
    S.box(860, 470, 280, 110, "Nitrogen (PSA)", [f"{f0(N2_NM3)} Nm3/h, 99.5%, {N2_P / 1e3:g} MPa abs", f"feed air {f0(n2['feed_air_nm3_h'])} Nm3/h (recovery {N2_RECOVERY:g}, assumed)", f"{f0(n2['electric_kW'])} kW, {f2(n2['specific_kWh_per_Nm3'])} kWh/Nm3", f"reversible minimum {f1(n2['min_work_kW'])} kW"], "unit")
    S.arrow([(1140, 388), (1215, 388)], "gas"); S.text(1146, 380, "to plant", "sm"); S.arrow([(1140, 525), (1215, 525)], "gas"); S.text(1146, 517, "to plant", "sm")
    S.arrow([(960, 340), (960, 286)], "cw"); S.text(966, 318, "air cooler duty", "sm")
    S.arrow([(860, 520), (835, 520), (835, 253), (860, 253)], "cw"); S.text(756, 512, "N2 cooler", "sm"); S.text(756, 526, "duty", "sm")
    S.box(20, 480, 730, 90, "Electricity and totals", [f"compressors + nitrogen: {f0(sm['compressor_shaft_kW'])} kW (air {f0(air['shaft_power_kW'])}, N2 {f0(n2['electric_kW'])})",
         f"cooling duty {f2(sm['cooling_duty_kW'] / 1e3)} MW -> circulation {f0(sm['cooling_water_m3_h'])} m3/h, make-up {f1(sm['cooling_tower_makeup_m3_h'])} m3/h",
         f"steam {f0(sm['steam_kg_h'])} kg/h, demin make-up {f0(sm['demin_makeup_kg_h'])} kg/h, turbine power lost {f2(lo['lost_power_MW'])} MW (gross {f2(lo['gross_lost_power_kW'] / 1e3)})"], "box")
    S.text(20, 620, "Illustrative inputs: 0.88 turbine efficiencies, 3 K heater TTD, 50% condensate return at 90 C, PSA recovery 0.45, header pressures, air/N2/other cooling demands, 1% blowdown, 85% demin recovery, 75% evaporative cooling, 4 cycles.", "note")
    S.text(20, 636, "Steam properties CoolProp; heater duty from DWSIM stream enthalpies; surrogate compounds stand in for the lumped pool. Screening only, not compared with plant data.", "note")
    S.text(20, 660, "Lines: orange steam, purple demin and condensate, blue cooling water, green gas. The link to the process heater is one-way: nothing here feeds back into the simulated flowsheet.", "note")
    return S.render()


def main():
    OUT.mkdir(parents=True, exist_ok=True); d = gather(); a, b = pfd(d), ufd(d)
    (OUT / "pfd.svg").write_text(a); (OUT / "ufd.svg").write_text(b)
    page = ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Refinery PFD and UFD</title>"
            "<style>body{margin:0;padding:16px;font:14px system-ui,sans-serif;background:#fff;color:#14202b}h1{font-size:18px}@media(prefers-color-scheme:dark){body{background:#14181c;color:#e8edf1}}"
            "section{max-width:1260px;margin:0 auto 24px}</style></head><body><section><h1>Process flow diagram</h1>" + a + "</section><section><h1>Utilities flow diagram</h1>" + b + "</section></body></html>")
    (OUT / "pfd_ufd.html").write_text(page); print("wrote", OUT)


if __name__ == "__main__":
    main()
