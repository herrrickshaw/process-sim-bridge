"""Independent cross-check of the DWSIM steam-cycle model (examples/doe_netl_b11a_steam_cycle.py) with CoolProp and tespy.

Run in a venv that has CoolProp and tespy (Python wheels; checked with CoolProp 8.0.0, tespy 0.12.1):
    python3 -m examples.dump_dwsim_rows dwsim_rows.json      # runs DWSIM (needs the container), writes the JSON
    python crosscheck_steam_cycle.py dwsim_rows.json
Reference state: liquid water at the triple point (~32 F), as in the NETL report. Report values are read by hand from the figure text.
"""
import sys
import json
import CoolProp.CoolProp as CP
d = json.load(open((sys.argv[1] if len(sys.argv) > 1 else "dwsim_rows.json")))
BTU = 2.326; F2K = lambda f: (f - 32) / 1.8 + 273.15; PSI = 6894.757
h = lambda T_F, P_psia: CP.PropsSI("H", "T", F2K(T_F), "P", P_psia * PSI, "Water") / 1000     # kJ/kg, CoolProp reference state
# NETL reference: liquid water at 32 F and 0.08865 psia
h0 = CP.PropsSI("H", "T", 273.16, "Q", 0, "Water") / 1000      # saturated liquid at the triple point (~32 F, 0.0886 psia)
print(f"CoolProp {CP.get_global_param_string('version')}  IAPWS-95 (HEOS Water); h(triple-point liquid) = {h0:.2f} kJ/kg (reference shift)")
print(f"{'stream':8}{'T F':>6}{'P psia':>8}{'report':>9}{'DWSIM':>9}{'CoolProp':>10}{'DWSIM-CP':>10}{'report-CP':>11}   (Btu/lb)")
worst = 0
for grp in ("condensate", "boiler"):
    for r in d[grp]:
        cp = (h(r["T_F"], r["P_psia"]) - h0) / BTU
        dw = r["H_dwsim_kJkg"] / BTU
        worst = max(worst, abs(dw - cp))
        print(f"{r['stream']:8}{r['T_F']:6}{r['P_psia']:8}{r['H_report']:9.0f}{dw:9.1f}{cp:10.1f}{dw-cp:10.2f}{r['H_report']-cp:11.2f}")
print(f"max |DWSIM - CoolProp| = {worst:.2f} Btu/lb")
# phase check for the hot well: saturation at 1 psia
print("Tsat at 1 psia =", round((CP.PropsSI('T','P',1*PSI,'Q',0,'Water')-273.15)*1.8+32,2), "F (report hot well 101 F)")

# tespy: same condensate train as a network, duties from m*dh vs CoolProp
from tespy.networks import Network
from tespy.components import Source, Sink, Pump, SimpleHeatExchanger
from tespy.connections import Connection
nw = Network(iterinfo=False)
nw.units.set_defaults(temperature="°C", pressure="bar", enthalpy="kJ/kg", mass_flow="kg/s", power="W", heat="W")
src, sink = Source("hotwell"), Sink("out")
pump = Pump("CP"); hx = [SimpleHeatExchanger(f"FWH{i}") for i in range(1, 5)]
rows = d["condensate"]; LB = 0.45359237; m = d["W_cond"] * LB / 3600
C = lambda a, ai, b, bi: Connection(a, ai, b, bi)
conns = [C(src, "out1", pump, "in1")] + [C(pump, "out1", hx[0], "in1")] + [C(hx[i], "out1", hx[i+1], "in1") for i in range(3)] + [C(hx[3], "out1", sink, "in1")]
nw.add_conns(*conns)
c = conns
f2c = lambda f: (f - 32) / 1.8; bar = lambda p: p * 0.06894757
c[0].set_attr(m=m, T=f2c(rows[0]["T_F"]), p=bar(rows[0]["P_psia"]), fluid={"water": 1})
pump.set_attr(eta_s=0.8)
c[1].set_attr(p=bar(rows[1]["P_psia"]))
for i, (cn, r) in enumerate(zip(conns[2:], rows[2:]), 0):
    cn.set_attr(T=f2c(r["T_F"]), p=bar(r["P_psia"]))
for i in range(4): pass
try:
    nw.solve("design"); nw.print_results() if False else None
    print("tespy solved. FWH duties (MW): ", [round(h_.Q.val / 1e6, 2) for h_ in hx])
    tot = sum(h_.Q.val for h_ in hx) / 1e6
    ref = m * (rows[-1]["H_report"] - rows[1]["H_report"]) * BTU / 1000
    print(f"sum duty tespy {tot:.2f} MW vs report m*dH {ref:.2f} MW; pump power tespy {pump.P.val/1e3:.1f} kW")
except Exception as e:
    print("tespy failed:", repr(e)[:300])
