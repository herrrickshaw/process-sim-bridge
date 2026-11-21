"""CLI: python3 -m hysys_bridge.casebook validate <dir> | run <case-id> [--reproduce] [--no-ledger] | hazop <study-id|path.json> [--out worksheet.md] | hazop-rules [parameter guide_word] | hazop-nodes <case-id|flowsheet.json> [--case CASE] [--sizes sizes.json] [--study-id id] [--out spec.json] | ledger <case-id>   (DWSIM_MCP_CMD for run; CASEBOOK_DIR for the case directory)"""
from __future__ import annotations
import glob, os, sys
from . import guardrails, hazop, hazop_nodes, ledger, runner, schema, tools


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
            v = "; ".join((f"{n} {x['simulated']:.4g} vs {x['reported']:.4g} ({100 * x['rel_err']:+.1f}%)" if x["rel_err"] is not None else f"{n} {x['simulated']:.4g} in {x['range']}: {'yes' if x['within_tol'] else 'NO'}" if "range" in x else f"{n} {x['simulated']:.4g} vs {x['reported']}") for n, x in o["values"].items())
            print(f"{o['scenario']:28} {o['package']:14} {v}  spec mismatches: {o['spec_mismatches'] or 'none'}  findings: {[f['code'] for f in o['findings']] or 'none'}  guardrails: {guardrails.summary(o.get('guardrails', []))}")
            for g in o.get("guardrails", []):
                if g["status"] in ("violation", "info"): print(f"    guardrail {g['status'].upper()} {g['rule']} {g['object']}: {g['detail']}")
        for scen, sp in run["package_spread_rel"].items(): print(f"package spread, {scen}: " + ", ".join(f"{n} {100 * x:.1f}%" for n, x in sp.items()))
        print(f"within tolerance in the paper's own package ({case['basis']['package_in_paper']}): {run['paper_package_within_tol']}; in every listed package: {run['all_within_tol']}")
        if "--no-ledger" not in argv: print(f"ledger rows written: {ledger.append(runner.ledger_rows(run))}")
        if "--reproduce" in argv:
            r = runner.reproduce(case, run); print(f"{'REPRODUCED' if r['matched'] == r['of'] else 'NOT REPRODUCED'} base {r['matched']}/{r['of']} SOLVED {r['solved']}/{r['total']}")
            return 0 if r["matched"] == r["of"] and r["solved"] == r["total"] else 1
        return 0
    if cmd == "hazop":
        spec = tools.load_spec(argv[1]) if not argv[1].endswith(".json") else __import__("json").load(open(argv[1])); case = tools._load(spec["case"]); probs = schema.validate(case) or hazop.validate_spec(spec, case)
        if probs: print("\n".join(probs)); return 1
        ws = hazop.run_study(spec, case); md = hazop.render_markdown(ws)
        if "--out" in argv: open(argv[argv.index("--out") + 1], "w").write(md + "\n"); print(f"worksheet written to {argv[argv.index('--out') + 1]}")
        else: print(md)
        return 0
    if cmd == "hazop-nodes":
        import json, copy
        flag = lambda k: argv[argv.index(k) + 1] if k in argv else None
        sizes = json.load(open(flag("--sizes"))) if flag("--sizes") else None; case = tools._load(flag("--case")) if flag("--case") else None; issues = None
        if argv[1].endswith(".json"):
            from ..ir import Flowsheet
            from .. import pid_reconcile
            fs = Flowsheet.from_json(argv[1]); issues = [str(i) for i in pid_reconcile.reconcile(copy.deepcopy(fs), fix=False)[0]]; g = hazop_nodes.graph_from_flowsheet(fs)
        else:
            case = tools._load(argv[1]); g = hazop_nodes.graph_from_case(case)
        spec = hazop_nodes.derive(g, case, flag("--study-id") or "draft-study", sizes, issues); d = spec["derivation"]
        text = json.dumps(spec, indent=1)
        if flag("--out"): open(flag("--out"), "w").write(text + "\n"); print(f"draft written to {flag('--out')}")
        print(f"{len(spec['nodes'])} node(s); complete: {d['complete']}; missing sizes: {len(d['missing_sizes'])}; mismatches: {len(d['mismatches'])}")
        for w in d["warnings"] + d["mismatches"] + d["errors"]: print("  -", w)
        if not flag("--out"): print(text)
        return 0
    if cmd == "hazop-rules":
        out = tools.t_hazop_rules({"parameter": argv[1], "guide_word": argv[2]} if len(argv) > 2 else {}); print(__import__("json").dumps(out, indent=1)); return 0 if out.get("valid") else 1
    if cmd == "ledger":
        case = tools._load(argv[1]); h = schema.case_hash(case); rows = [r for r in ledger.read() if r["case"] == case["id"] and r["case_hash"] == h]
        print(f"LEDGER ROWS {len(rows)} for {case['id']} hash {h}"); return 0
    print(__doc__); return 2


if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
