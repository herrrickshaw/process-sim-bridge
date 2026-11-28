"""Model parts of the DOE/NETL Case B11A subcritical PC steam cycle in DWSIM and compare enthalpies with the report.

Source (US Government work, public domain): NETL, "Cost and Performance Baseline for Fossil Energy Plants, Volume 1: Bituminous
Coal and Natural Gas to Electricity", Revision 4 (2019), OSTI 1569246, Exhibit 4-26 (Case B11A energy and mass balance, SubC steam
cycle). Values below were read by hand from that exhibit's text layer: flow lb/hr (W), temperature F (T), absolute pressure psia (P),
enthalpy Btu/lb (H; reference: liquid water at 32 F and 0.08865 psia). Needs the DWSIM MCP server (see hysys_bridge/dwsim/tools.py).

    DWSIM_MCP_CMD="podman run -i --rm --network none ghcr.io/danwbr/dwsim-mcp:latest --stdio" python3 -m examples.doe_netl_b11a_steam_cycle
"""
import os, shlex, sys
from hysys_bridge import hysys_writer
from hysys_bridge.dwsim.backend import DwsimBackend, StdioTransport
from hysys_bridge.ir import Flowsheet, Stream, Unit

LB, F2C, PSI = 0.45359237, lambda f: (f - 32) / 1.8, 6.894757
BTU_LB = 2.326                      # kJ/kg per Btu/lb
CMD = shlex.split(os.environ.get("DWSIM_MCP_CMD", "podman run -i --rm --network none ghcr.io/danwbr/dwsim-mcp:latest --stdio"))

def S(sid, kind, src, dst, w=None, t=None, p=None):
    return Stream(sid, kind, src, dst, T_C=None if t is None else F2C(t), P_kPa=None if p is None else p * PSI,
                  mass_flow_kg_h=None if w is None else w * LB, composition={"Water": 1.0} if kind == "feed" else {}, composition_basis="mass")

# stream -> (T F, P psia, report H Btu/lb)
CONDENSATE = {"HOTWELL": (101, 1, 69), "CP_OUT": (101, 191, 70), "FWH1": (125, 183, 93), "FWH2": (160, 176, 129), "FWH3": (200, 169, 168), "FWH4": (246, 162, 215)}
W_COND = 3_304_179

def condensate_train():
    fs = Flowsheet("condensate_train", "Steam Tables", ["Water"])
    fs.streams = {"HOTWELL": S("HOTWELL", "feed", None, "CP", W_COND, 101, 1)}
    names = list(CONDENSATE)
    for i, n in enumerate(names[1:], 1):
        T, P, _ = CONDENSATE[n]
        fs.streams[n] = S(n, "product" if i == len(names) - 1 else "intermediate", "CP" if i == 1 else f"H{i-1}", None if i == len(names) - 1 else f"H{i}", None, T, P)
    fs.units = {"CP": Unit("CP", "pump")}
    fs.units.update({f"H{i}": Unit(f"H{i}", "heater") for i in range(1, 5)})
    fs.relink(); return fs

BOILER_IN, BOILER_OUT, W_BOILER = (486, 2536, 471), (1050, 2415, 1494), 4_120_442

def boiler_section():
    fs = Flowsheet("boiler_main_steam", "Steam Tables", ["Water"])
    fs.streams = {"BFW": S("BFW", "feed", None, "BLR", W_BOILER, BOILER_IN[0], BOILER_IN[1]),
                  "MS": S("MS", "product", "BLR", None, None, BOILER_OUT[0], BOILER_OUT[1])}
    fs.units = {"BLR": Unit("BLR", "heater")}; fs.relink(); return fs

def run(fs, expect):
    t = StdioTransport(CMD)
    try:
        be = DwsimBackend(t); hysys_writer.write(fs, be)
        ok = be.solve()
        print(f"\n{fs.name}: solved={ok}", "" if ok else be.last_solve)
        if not ok: return None
        rows = []
        for sid, (T, P, H) in expect.items():
            r = be.read_stream(sid); mix = be._c("stream_results", name=sid)
            h = next(ph for ph in mix["phases"] if ph["name"] == "Mixture")["enthalpy_kJ_kg"]
            rows.append((sid, T, P, H, h, r["T"], r["P"]))
        return rows, be.check_solution()
    finally:
        t.close()

def show(rows, mism):
    base = rows[1][4] if rows[1][0] == "CP_OUT" else rows[0][4]; base_r = rows[1][3] if rows[1][0] == "CP_OUT" else rows[0][3]
    print(f"{'stream':8} {'T F':>6} {'P psia':>7} {'H report':>9} {'H DWSIM abs':>12} {'dH vs ref pt (report | DWSIM) Btu/lb'}")
    for sid, T, P, H, h, tc, pk in rows:
        print(f"{sid:8} {T:6} {P:7} {H:9.0f} {h/BTU_LB:12.1f}   {H-base_r:7.1f} | {(h-base)/BTU_LB:7.1f}   (DWSIM T {tc*1.8+32:.1f} F, P {pk/PSI:.1f} psia)")
    print("spec-vs-result mismatches:", mism or "none")

if __name__ == "__main__":
    out = run(condensate_train(), CONDENSATE)
    if out: show(*out)
    out = run(boiler_section(), {"BFW": (*BOILER_IN[:2], BOILER_IN[2]), "MS": (*BOILER_OUT[:2], BOILER_OUT[2])})
    if out:
        rows, mism = out; (_, _, _, h0r, h0, *_), (_, _, _, h1r, h1, *_) = rows
        print(f"main-steam boiler: report dH {h1r-h0r} Btu/lb, DWSIM dH {(h1-h0)/BTU_LB:.1f} Btu/lb; mismatches: {mism or 'none'}")
