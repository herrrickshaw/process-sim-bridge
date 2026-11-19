"""Compare an andreasen_rerun.py result file with the paper's DWSIM 7 and Aspen HYSYS results.  python examples/andreasen_stats.py <clone> <rerun.json>"""
import sys, json
import numpy as np
clone, f = sys.argv[1], sys.argv[2]
ref = np.loadtxt(f"{clone}/data/DWSIM_result.csv", delimiter=","); hys = np.loadtxt(f"{clone}/data/HYSYS_result.csv", delimiter=",")
out = np.array(json.load(open(f)), dtype=float)            # rows: solved, crude flow (kmol/h), power (kW), RVP (psi)
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
