"""CLI: python3 -m hysys_bridge.casebook validate <dir> | run <case-id> [--reproduce] [--no-ledger] | ledger <case-id>   (DWSIM_MCP_CMD for run; CASEBOOK_DIR for the case directory)"""
from __future__ import annotations
import glob, os, sys
from . import ledger, runner, schema, tools


def main(argv):
    if not argv: print(__doc__); return 2
    cmd = argv[0]
    if cmd == "validate":
        d = argv[1] if len(argv) > 1 else tools._dir(); bad = 0; files = sorted(glob.glob(os.path.join(d, "*.json")))
        for f in files:
            probs = schema.validate(schema.load(f))
            for x in probs: print(f"{os.path.basename(f)}: {x}")
            bad += bool(probs)
        if bad or not files: print(f"CASEBOOK INVALID ({bad} bad of {len(files)} files)"); return 1
        print(f"CASEBOOK VALID {len(files)} case(s)"); return 0
    if cmd == "run":
        case = tools._load(argv[1]); probs = schema.validate(case)
        if probs: print("\n".join(probs)); return 1
        run = runner.run_case(case)
        for o in run["results"]:
            if not o["solved"]: print(f"{o['scenario']:28} {o['package']:14} did not solve: {o['why']}\n  next step: {o['next_step']}"); continue
            v = "; ".join(f"{n} {x['simulated']:.4g} vs {x['reported']:.4g} ({100 * x['rel_err']:+.1f}%)" for n, x in o["values"].items())
            print(f"{o['scenario']:28} {o['package']:14} {v}  spec mismatches: {o['spec_mismatches'] or 'none'}  findings: {[f['code'] for f in o['findings']] or 'none'}")
        for scen, sp in run["package_spread_rel"].items(): print(f"package spread, {scen}: " + ", ".join(f"{n} {100 * x:.1f}%" for n, x in sp.items()))
        if "--no-ledger" not in argv: print(f"ledger rows written: {ledger.append(runner.ledger_rows(run))}")
        if "--reproduce" in argv:
            r = runner.reproduce(case, run); print(f"{'REPRODUCED' if r['matched'] == r['of'] else 'NOT REPRODUCED'} base {r['matched']}/{r['of']} SOLVED {r['solved']}/{r['total']}")
            return 0 if r["matched"] == r["of"] and r["solved"] == r["total"] else 1
        return 0
    if cmd == "ledger":
        case = tools._load(argv[1]); h = schema.case_hash(case); rows = [r for r in ledger.read() if r["case"] == case["id"] and r["case_hash"] == h]
        print(f"LEDGER ROWS {len(rows)} for {case['id']} hash {h}"); return 0
    print(__doc__); return 2


if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
