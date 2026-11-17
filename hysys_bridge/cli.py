"""python -m hysys_bridge.cli <hmb.csv|hmb.pdf> [--out case.json] [--mock] [--audit audit.csv]"""
import argparse, sys
import csv
from . import extract_hmb, normalize, validate, hysys_writer, hmb_check, ocr, pid_extract, pid_reconcile, pid_eval, dexpi_export
from .ir import Flowsheet
from .backend import MockHysys


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("hmb"); ap.add_argument("--out", default="case.json")
    ap.add_argument("--package", default="Peng-Robinson")
    ap.add_argument("--audit", default="audit.csv")
    ap.add_argument("--mock", action="store_true", help="dry run, no HYSYS")
    ap.add_argument("--scanned", action="store_true", help="OCR a scanned PDF H&MB")
    ap.add_argument("--accept-review", action="store_true", help="OCR review list was checked by a human")
    ap.add_argument("--pid", help="P&ID image/PDF: extract topology draft and merge H&MB values")
    ap.add_argument("--dexpi", help="also write the flowsheet as DEXPI-style Proteus XML (unvalidated, see dexpi_export.py)")
    ap.add_argument("--dexpi-process", help="also write the DEXPI Process model (streams, composition) as pyDEXPI JSON; needs pydexpi")
    ap.add_argument("--truth", help="ground-truth flowsheet JSON: score the extracted P&ID topology against it")
    ap.add_argument("--accept-topology", action="store_true", help="P&ID topology was signed off")
    a = ap.parse_args(argv)
    if a.scanned:
        rows, review = ocr.ocr_pdf(a.hmb)
        with open("review.csv", "w", newline="") as f:
            w = csv.writer(f); w.writerow(["row", "col", "text", "conf"]); w.writerows(review)
        with open("ocr_rows.csv", "w", newline="") as f: csv.writer(f).writerows(rows)
        if review and not a.accept_review:
            print(f"BLOCKED: {len(review)} low-confidence OCR cells -> review.csv. Correct ocr_rows.csv, "
                  "re-run on it (no --scanned) or pass --accept-review"); return 4
        fs = extract_hmb.from_rows(rows, origin=a.hmb)
    else:
        fs = (extract_hmb.from_pdf if a.hmb.lower().endswith(".pdf") else extract_hmb.from_csv)(a.hmb)
    if a.pid:
        topo = pid_extract.extract(a.pid)
        issues, acts = pid_reconcile.reconcile(topo, fix=True)
        for x in acts: print("reconcile (auto-fix):", x)
        for x in issues: print("reconcile:", x)
        if a.truth:
            print("score:", pid_eval.score(topo, Flowsheet.from_json(a.truth)))
        if any(i.level == "error" for i in issues) and not a.accept_topology:
            topo.to_json(a.out); print(f"BLOCKED: reconciliation errors in P&ID topology; see {a.out}"); return 6
        for n in pid_extract.merge_values(topo, fs): print("merge:", n)
        flagged = [u.id for u in topo.units.values() if "needs-signoff" in u.flags]
        if flagged and not a.accept_topology:
            topo.to_json(a.out); print(f"BLOCKED: P&ID topology is a draft ({len(flagged)} units); review {a.out}, "
                                       "then re-run with --accept-topology"); return 5
        fs = topo
    fs.fluid_package = a.package
    for line in normalize.normalize(fs): print("normalize:", line)
    if a.dexpi: dexpi_export.export(fs, a.dexpi); print("wrote", a.dexpi)
    if a.dexpi_process:
        import os
        from . import dexpi_process
        d, f = os.path.split(os.path.abspath(a.dexpi_process)); dexpi_process.export_json(fs, d, f); print("wrote", a.dexpi_process)
    issues = validate.validate(fs)
    for i in issues: print(i)
    fs.to_json(a.out)
    if validate.blocking(issues):
        print(f"\nBLOCKED: fix {len(validate.blocking(issues))} error(s); IR saved to {a.out} for review"); return 2
    be = MockHysys() if a.mock else __import__("hysys_bridge.backend", fromlist=["x"]).HysysCOM()
    rows = hysys_writer.write(fs, be, a.audit)
    bad = [r for r in rows if r.status != "OK"]
    print(f"wrote {len(rows)} values, {len(bad)} read-back mismatches -> {a.audit}")
    if bad: return 3
    if be.solve():
        d = [x for x in hmb_check.check(fs, be) if not x.ok]
        print(f"post-solve: {len(d)} H&MB disagreements")
        for x in d: print("  ", x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
