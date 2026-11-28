"""VLE benchmark of DWSIM thermodynamic packages through our backend, against CoolProp and a literature value.

Runs in a venv with CoolProp (checked with CoolProp 8.0.0) and needs the DWSIM MCP container:
    /path/to/venv/bin/python -m examples.vle_benchmark

Method: a feed is heated/cooled to (T, P) in a DWSIM Heater (verified unit) and the outlet stream's phases are read, so every point is
a T-P flash of the chosen package. Reference values:
  A) propane / n-butane, z = 0.5 mole, 500 kPa: CoolProp HEOS mixture model (a reference-quality CALCULATION fitted to data, not raw measurements).
  B) ethanol / water at 101.325 kPa: the ethanol-water azeotrope, 78.15 C at 89.4 mole% ethanol (widely tabulated textbook value; pure
     ethanol 78.3 C, water 100 C). Raw experimental data sets are paywalled (NIST SRD 93, DECHEMA) or not checked; see docs/THERMO_SIMULATION_SURVEY.md.
"""
import os, shlex, json
import CoolProp.CoolProp as CP
from hysys_bridge import hysys_writer
from hysys_bridge.dwsim.backend import DwsimBackend, StdioTransport
from hysys_bridge.ir import Flowsheet, Stream, Unit

CMD = shlex.split(os.environ.get("DWSIM_MCP_CMD", "podman run -i --rm --network none ghcr.io/danwbr/dwsim-mcp:latest --stdio"))
MW = {"Propane": 44.097, "N-butane": 58.123, "Ethanol": 46.069, "Water": 18.015}
CP_NAME = {"Propane": "Propane", "N-butane": "N-butane"}

def mass_fracs(z):
    m = {c: z[c] * MW[c] for c in z}; t = sum(m.values()); return {c: v / t for c, v in m.items()}

def flash(t, package, z, T_C, P_kPa):
    """T-P flash in DWSIM via a Heater; returns (vapour mole fraction, liquid mole fractions, vapour mole fractions)."""
    comps = list(z)
    fs = Flowsheet("vle", package, comps)
    fs.streams = {"IN": Stream("IN", "feed", None, "HX", T_C=min(T_C, 15.0) if T_C > 15 else T_C - 5, P_kPa=P_kPa, mass_flow_kg_h=3600.0, composition=mass_fracs(z), composition_basis="mass"),
                  "OUT": Stream("OUT", "product", "HX", None, T_C=T_C, P_kPa=P_kPa)}
    fs.units = {"HX": Unit("HX", "heater")}; fs.relink()
    be = DwsimBackend(t); hysys_writer.write(fs, be)
    if not be.solve(): raise RuntimeError(f"{package} T={T_C}: {be.last_solve}")
    r = be._c("stream_results", name="OUT"); ph = {p["name"]: p for p in r["phases"]}
    t.call("dwsim_flowsheet_close", {"flowsheet_id": be.fid})            # free the flowsheet: hundreds of open ones exhausted the container
    vf = ph["Vapor"]["fraction"]
    comp = lambda name: {c: ph[name]["compounds"][c]["mole_fraction"] for c in comps} if name in ph else None
    return vf, comp("Liquid1"), comp("Vapor")

def bubble_T(t, package, z, P_kPa, lo=40.0, hi=120.0, tol=0.02):
    """Lowest T at which vapour appears (VF > 1e-4), by bisection."""
    for _ in range(40):
        mid = (lo + hi) / 2
        vf = flash(t, package, z, mid, P_kPa)[0]
        lo, hi = (mid, hi) if vf <= 1e-4 else (lo, mid)
        if hi - lo < tol: break
    return (lo + hi) / 2

def case_A(t):
    z = {"Propane": 0.5, "N-butane": 0.5}; P = 500.0
    s = CP.AbstractState("HEOS", "Propane&n-Butane"); s.set_mole_fractions([0.5, 0.5])
    s.update(CP.PQ_INPUTS, P * 1e3, 0); Tb = s.T() - 273.15
    s.update(CP.PQ_INPUTS, P * 1e3, 1); Td = s.T() - 273.15
    T = (Tb + Td) / 2
    s.update(CP.PT_INPUTS, P * 1e3, T + 273.15); x0, y0 = s.mole_fractions_liquid()[0], s.mole_fractions_vapor()[0]; ref = ((0.5 - x0) / (y0 - x0), x0, y0)   # VF by lever rule
    print(f"\nA) propane/n-butane z=0.5, P=500 kPa; CoolProp bubble {Tb:.2f} C, dew {Td:.2f} C; flash at {T:.2f} C")
    print(f"{'package':14}{'VF':>8}{'x_C3':>8}{'y_C3':>8}   (CoolProp VF {ref[0]:.3f}, x {ref[1]:.3f}, y {ref[2]:.3f})")
    out = {}
    for pkg in ("Peng-Robinson (PR)", "Soave-Redlich-Kwong (SRK)", "Raoult's Law"):
        vf, x, y = flash(t, pkg, z, T, P)
        out[pkg] = (vf, x["Propane"], y["Propane"])
        print(f"{pkg:14}{vf:8.3f}{x['Propane']:8.3f}{y['Propane']:8.3f}   dVF {vf-ref[0]:+.3f} dx {x['Propane']-ref[1]:+.3f} dy {y['Propane']-ref[2]:+.3f}")
    return {"ref": ref, "T": T, "dwsim": out}

def case_B(_t):
    P = 101.325
    print("\nB) ethanol/water at 101.325 kPa: DWSIM bubble temperature (C); literature: pure ethanol 78.3, azeotrope 78.15 at x=0.894, pure water 100.0")
    print(f"{'package':14}{'x=0 (water)':>14}{'x=0.894':>10}{'x=1 (EtOH)':>12}")
    out = {}
    for pkg in ("NRTL", "UNIQUAC", "Wilson", "Peng-Robinson (PR)", "Raoult's Law"):
        t = StdioTransport(CMD)                                           # fresh server per package
        try:
            row = [bubble_T(t, pkg, {"Ethanol": x, "Water": 1 - x}, P) for x in (1e-6, 0.894, 1 - 1e-6)]
            out[pkg] = row
            print(f"{pkg:20}{row[0]:10.2f}{row[1]:10.2f}{row[2]:12.2f}")
        except Exception as e:
            out[pkg] = f"failed: {str(e)[:120]}"; print(f"{pkg:20} FAILED: {str(e)[:120]}")
        finally:
            try: t.close()
            except Exception: pass
    return out

if __name__ == "__main__":
    t = StdioTransport(CMD)
    try:
        res = {"A": case_A(t), "B": case_B(t)}
        json.dump(res, open("vle_benchmark_results.json", "w"), indent=1, default=str)
    finally:
        t.close()
