"""Score DWSIM thermodynamic packages (and CalebBell `thermo` as a second reference) against free ThermoML experimental VLE data.

Data: NIST/TRC ThermoML record for Tsanas et al., Fluid Phase Equilib. 2014, 379, 148-156 (ethanol/water at 101.3 kPa, ebulliometer; 7 points,
liquid mole fraction of ethanol 0.683-0.96): boiling temperature, and vapour mole fraction. The XML is downloaded at run time from
https://trc.nist.gov/ThermoML/10.1016/j.fluid.2014.07.022.xml into the cache folder (not stored in the repo).
Run (venv with `thermo` and `CoolProp` not needed here; DWSIM container needed):
    /path/to/venv/bin/python -m examples.thermoml_vle_score [cache_dir]
Caveat: only 7 points, all near the azeotrope, one pressure, one lab: a sanity check on packages, not a full validation.
"""
import os, sys, urllib.request
import xml.etree.ElementTree as ET
from examples.vle_benchmark import CMD, flash, bubble_T, StdioTransport
from examples import thermo_reference as TR

URL = "https://trc.nist.gov/ThermoML/10.1016/j.fluid.2014.07.022.xml"
NS = {"t": "http://www.iupac.org/namespaces/ThermoML"}
PACKAGES = ["NRTL", "UNIQUAC", "Wilson", "Peng-Robinson (PR)", "Raoult's Law"]

def load(cache):
    os.makedirs(cache, exist_ok=True); path = os.path.join(cache, "tsanas2014.xml")
    if not os.path.exists(path):
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"}); open(path, "wb").write(urllib.request.urlopen(req, timeout=60).read())
    root = ET.parse(path).getroot(); blocks = []
    for d in root.findall("t:PureOrMixtureData", NS)[:2]:                 # the two binary ethanol/water blocks at 101.3 kPa
        blocks.append([(float(v.find("t:VariableValue/t:nVarValue", NS).text), float(v.find("t:PropertyValue/t:nPropValue", NS).text)) for v in d.findall("t:NumValues", NS)])
    return blocks[0], blocks[1]                                           # (x, Tb [K]), (x, y)

def stats(err): n = len(err); return sum(err) / n, sum(abs(e) for e in err) / n, max(abs(e) for e in err)

if __name__ == "__main__":
    tb, yv = load(sys.argv[1] if len(sys.argv) > 1 else ".cache_thermoml")
    xs = [x for x, _ in tb]; assert xs == [x for x, _ in yv]
    print("experimental (x_EtOH, Tb C, y_EtOH):", [(x, round(T - 273.15, 2), y) for (x, T), (_, y) in zip(tb, yv)])
    rows = {}
    for pkg in PACKAGES:
        t = StdioTransport(CMD)
        try:
            Ts, ys = [], []
            for x in xs:
                z = {"Ethanol": x, "Water": 1 - x}; Tc = bubble_T(t, pkg, z, 101.325, lo=70.0, hi=90.0, tol=0.01)
                Ts.append(Tc); ys.append(flash(t, pkg, z, Tc + 0.03, 101.325)[2]["Ethanol"])
            rows["DWSIM " + pkg] = (Ts, ys)
        except Exception as e: print(pkg, "FAILED:", str(e)[:120])
        finally:
            try: t.close()
            except Exception: pass
    for model in ("NRTL", "PR"):
        fl = TR.make(model); Ts, ys = [], []
        for x in xs: T, y = TR.bubble(fl, x, lo=340.0, hi=370.0); Ts.append(T - 273.15); ys.append(y)
        rows["thermo " + model] = (Ts, ys)
    print(f"\n{'model':26}{'bias T':>8}{'MAE T':>8}{'max T':>8}   {'bias y':>8}{'MAE y':>8}   (C, mole fraction; model - experiment)")
    for name, (Ts, ys) in rows.items():
        et = [Tc - (Te - 273.15) for Tc, (_, Te) in zip(Ts, tb)]; ey = [yc - ye for yc, (_, ye) in zip(ys, yv)]
        bt, mt, xt = stats(et); by, my, _ = stats(ey)
        print(f"{name:26}{bt:8.2f}{mt:8.2f}{xt:8.2f}   {by:8.3f}{my:8.3f}")
