"""Compare an andreasen_rerun.py result file with the paper's DWSIM 7 and Aspen HYSYS results.  python examples/andreasen_stats.py <clone> <rerun.json>"""
import sys, json
import numpy as np
clone, f = sys.argv[1], sys.argv[2]
ref = np.loadtxt(f"{clone}/data/DWSIM_result.csv", delimiter=","); hys = np.loadtxt(f"{clone}/data/HYSYS_result.csv", delimiter=",")
out = np.array(json.load(open(f)), dtype=float)            # rows: solved, crude flow (kmol/h), power (kW), RVP (psi) [, vapour ratio before, after the solve]
n = len(out); ok = out[:, 0] == 1
bad_ref = (ref[:n, :3] == -9999).any(axis=1)                # the paper's script writes -9999 for cases that did not solve in its DWSIM 7
stale = np.r_[False, (ref[1:n, :3] == ref[:n - 1, :3]).all(axis=1)] & ~bad_ref   # a row identical to the previous one = stale solver state in the paper's run
bad_ref |= stale
print(f"cases {n}: ours solved {int(ok.sum())}; paper's DWSIM 7 unusable (-9999 or a row identical to the previous one) on {int(bad_ref.sum())}: {[int(i) for i in np.where(bad_ref)[0]]}; ours unsolved: {[int(i) for i in np.where(~ok)[0]]}")
okd = ok & ~bad_ref                                          # rows usable against the paper's DWSIM results
print(f"rows compared with paper DWSIM 7: {int(okd.sum())}; with paper HYSYS: {int(ok.sum())}")
names = ["crude flow", "power", "RVP"]
for j, name in enumerate(names):
    for lab, mask, tab in (("paper DWSIM 7", okd, ref), ("paper HYSYS", ok, hys)):
        if tab.shape[1] <= j: continue
        mine, other = out[mask, j + 1], tab[:n][mask, j]
        rel = (mine - other) / other * 100
        print(f"{name:11} vs {lab:14}: mean {rel.mean():+.3f}%  MAE {np.abs(rel).mean():.3f}%  max |{np.abs(rel).max():.2f}|%  r = {np.corrcoef(mine, other)[0, 1]:.5f}")
for j, name in enumerate(names):
    m = ~bad_ref
    rel = (ref[:n][m, j] - hys[:n][m, j]) / hys[:n][m, j] * 100
    print(f"(for scale) paper DWSIM 7 vs paper HYSYS, {name}: MAE {np.abs(rel).mean():.3f}%  max {np.abs(rel).max():.2f}%")

if out.shape[1] >= 6:                                        # vapour ratio: the paper's script reads it BEFORE the solve, so its row i is the state left by case i-1
    vb, va = out[:, 4], out[:, 5]
    rows = ~bad_ref & np.isfinite(vb) & (ref[:n, 3] > 0)
    rel_b = (vb[rows] - ref[:n][rows, 3]) / ref[:n][rows, 3] * 100
    print(f"vapour ratio, ours read before the solve (paper-faithful) vs paper DWSIM 7: rows {int(rows.sum())}  MAE {np.abs(rel_b).mean():.4f}%  max {np.abs(rel_b).max():.3f}%  r = {np.corrcoef(vb[rows], ref[:n][rows, 3])[0, 1]:.5f}")
    idx = np.arange(1, n); m2 = (~bad_ref[idx]) & (~bad_ref[idx - 1]) & np.isfinite(va[idx - 1]) & (ref[idx, 3] > 0)
    rel_a = (va[idx - 1][m2] - ref[idx, 3][m2]) / ref[idx, 3][m2] * 100
    print(f"vapour ratio, ours after solve of case i-1 vs paper row i (lag check):        rows {int(m2.sum())}  MAE {np.abs(rel_a).mean():.4f}%  max {np.abs(rel_a).max():.3f}%")
    rel_n = (va[1:][m2] - ref[1:n, 3][m2]) / ref[1:n, 3][m2] * 100
    print(f"vapour ratio, ours after solve of case i vs paper row i (no lag):             rows {int(m2.sum())}  MAE {np.abs(rel_n).mean():.4f}%  max {np.abs(rel_n).max():.3f}%")
