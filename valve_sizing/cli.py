"""python -m valve_sizing.cli {levels|gas|steam|liquid|fire|thermal|control-liquid|control-gas} ..."""
import argparse, json, sys
from . import relief, control, pressure


def main(argv=None):
    ap = argparse.ArgumentParser(prog="valve_sizing")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--mawp", type=float, required=True, help="kPag")
        p.add_argument("--set", type=float, dest="set_pressure", help="kPag (default = MAWP)")
        p.add_argument("--scenario", default="single", choices=["single", "multiple", "fire"])
        p.add_argument("--operating", type=float, help="kPag, for the 90%% set-pressure check")
    p = sub.add_parser("levels"); common(p); p.add_argument("--lsr", type=float, default=1.0)
    p = sub.add_parser("gas"); common(p)
    for a in ("w", "T", "mw", "k"): p.add_argument(f"--{a}", type=float, required=True)
    p.add_argument("--z", type=float, default=1.0); p.add_argument("--backpressure", type=float, default=0.0)
    p.add_argument("--kb", type=float, default=1.0)
    p = sub.add_parser("steam"); common(p); p.add_argument("--w", type=float, required=True); p.add_argument("--ksh", type=float, default=1.0)
    p = sub.add_parser("liquid"); common(p); p.add_argument("--q", type=float, required=True, help="m3/h")
    p.add_argument("--sg", type=float, required=True); p.add_argument("--visc", type=float, default=1.0)
    p.add_argument("--backpressure", type=float, default=0.0)
    p = sub.add_parser("fire"); p.add_argument("--area", type=float, required=True, help="wetted m2")
    p.add_argument("--latent", type=float, required=True, help="kJ/kg"); p.add_argument("--F", type=float, default=1.0)
    p.add_argument("--poor-drainage", action="store_true")
    p = sub.add_parser("control-liquid")
    for a in ("q", "p1", "p2", "sg", "pv", "pc"): p.add_argument(f"--{a}", type=float, required=True)
    p.add_argument("--FL", type=float, default=0.9)
    p = sub.add_parser("control-gas")
    for a in ("w", "p1", "p2", "T", "mw", "k"): p.add_argument(f"--{a}", type=float, required=True)
    p.add_argument("--z", type=float, default=1.0); p.add_argument("--xT", type=float, default=0.7)
    a = ap.parse_args(argv)
    if a.cmd == "levels":
        print(json.dumps(pressure.levels(a.mawp, a.set_pressure, a.scenario, a.operating, a.lsr).__dict__, indent=2))
    elif a.cmd == "gas":
        print(relief.size_gas(a.w, a.T, a.mw, a.k, a.z, a.mawp, a.set_pressure, a.scenario, a.backpressure, kb=a.kb, operating=a.operating))
    elif a.cmd == "steam":
        print(relief.size_steam(a.w, a.mawp, a.set_pressure, a.scenario, a.ksh, operating=a.operating))
    elif a.cmd == "liquid":
        print(relief.size_liquid(a.q, a.sg, a.mawp, a.set_pressure, a.scenario, a.backpressure, a.visc, operating=a.operating))
    elif a.cmd == "fire":
        print(relief.fire_vapour_rate(a.area, a.latent, a.F, not a.poor_drainage))
    elif a.cmd == "control-liquid":
        print(control.liquid(a.q, a.p1, a.p2, a.sg, a.pv, a.pc, a.FL))
    elif a.cmd == "control-gas":
        print(control.gas(a.w, a.p1, a.p2, a.T, a.mw, a.k, a.z, a.xT))


if __name__ == "__main__":
    sys.exit(main())
