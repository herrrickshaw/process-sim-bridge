"""Model the alkylator feed heater of a student cumene/phenol/acetone plant design and compare duty with its HYSYS result.

Source: third-party upload on pdfcoffee.com, "PLANT DESIGN MANUSCRIPT" (production of phenol and acetone from propylene and benzene
via the cumene process, Aspen HYSYS V8; student report, copyright its author). Only process conditions (facts) are used here, no text:
  stream "To Heater":  liquid, 72.429 C, 34.38675 bar_g, 13,810.09 kmol/h, 1,071,616 kg/h, heat flow 7.49e8 kJ/h
  stream "To_Alkylator": 170 C, 33.766222 bar_g, heat flow 9.6e8 kJ/h;  report energy stream Q-Heater100 = 210,583,600.9 kJ/h
  fluid package in the report: NRTL.   Gauge pressures -> absolute by +1.01325 bar.
Composition is RECONSTRUCTED, because the report's composition table is scrambled in the page text: propylene mole fraction 0.00574 (read
from the table and confirmed by a mole balance on the mixer feeds: 79.67 kmol/h x 0.990453 / 13,810 kmol/h = 0.00571), balance benzene.
That composition gives 77.9 kg/kmol vs the report's 1,071,616 / 13,810 = 77.6, so ~0.4% of the stream's makeup is unexplained (small
cumene/propane content would change it). The mass flow is therefore taken from the report, not the mole flow.

    python3 -m examples.cumene_alkylator_feed_heater
"""
import os, shlex
from hysys_bridge import hysys_writer
from hysys_bridge.dwsim.backend import DwsimBackend, StdioTransport
from hysys_bridge.ir import Flowsheet, Stream, Unit

CMD = shlex.split(os.environ.get("DWSIM_MCP_CMD", "podman run -i --rm --network none ghcr.io/danwbr/dwsim-mcp:latest --stdio"))
ATM_BAR = 1.01325
MW = {"Benzene": 78.114, "Propylene": 42.081}
X_PROP = 0.00574
REPORT = {"T_in": 72.429121, "T_out": 170.0, "P_in_barg": 34.38675, "P_out_barg": 33.766222, "mass_kgh": 1_071_616.0,
          "H_in": 7.49e8, "H_out": 9.60e8, "Q": 210_583_600.9}

def mass_fractions():
    m = {"Propylene": X_PROP * MW["Propylene"], "Benzene": (1 - X_PROP) * MW["Benzene"]}
    tot = sum(m.values()); return {k: v / tot for k, v in m.items()}

def flowsheet(package):
    fs = Flowsheet("cumene_feed_heater", package, ["Benzene", "Propylene"])
    fs.streams = {
        "TO_HEATER": Stream("TO_HEATER", "feed", None, "HE100", T_C=REPORT["T_in"], P_kPa=(REPORT["P_in_barg"] + ATM_BAR) * 100,
                            mass_flow_kg_h=REPORT["mass_kgh"], composition=mass_fractions(), composition_basis="mass"),
        "TO_ALKYLATOR": Stream("TO_ALKYLATOR", "product", "HE100", None, T_C=REPORT["T_out"], P_kPa=(REPORT["P_out_barg"] + ATM_BAR) * 100)}
    fs.units = {"HE100": Unit("HE100", "heater")}; fs.relink(); return fs

def run(package):
    t = StdioTransport(CMD)
    try:
        be = DwsimBackend(t); hysys_writer.write(flowsheet(package), be)
        if not be.solve(): return {"package": package, "solved": False, "why": be.last_solve}
        res = {s: be._c("stream_results", name=s) for s in ("TO_HEATER", "TO_ALKYLATOR")}
        hk = {s: next(p for p in r["phases"] if p["name"] == "Mixture")["enthalpy_kJ_kg"] for s, r in res.items()}
        kg_h = res["TO_HEATER"]["mass_flow_kg_s"] * 3600
        q = (hk["TO_ALKYLATOR"] - hk["TO_HEATER"]) * kg_h
        phases = {s: [(p["name"], round(p["fraction"], 3)) for p in r["phases"] if p["name"] in ("Vapor", "OverallLiquid") and p["fraction"] > 0] for s, r in res.items()}
        return {"package": package, "solved": True, "Q_kJ_h": q, "T_out_C": res["TO_ALKYLATOR"]["temperature_K"] - 273.15, "phases": phases,
                "mismatches": be.check_solution()}
    finally:
        t.close()

if __name__ == "__main__":
    print(f"report: Q-Heater100 = {REPORT['Q']:.4g} kJ/h; enthalpy rise {REPORT['H_out'] - REPORT['H_in']:.4g} kJ/h (stream table, 3 digits)")
    for pkg in ("NRTL", "Peng-Robinson", "SRK"):
        r = run(pkg)
        if not r["solved"]: print(pkg, "did not solve:", r["why"]); continue
        print(f"{pkg:14} Q = {r['Q_kJ_h']:.4g} kJ/h  ({100 * (r['Q_kJ_h'] / REPORT['Q'] - 1):+.1f}% vs report)  phases {r['phases']}  spec mismatches: {r['mismatches'] or 'none'}")
