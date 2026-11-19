"""Compare an andreasen_rerun.py result file with the paper's DWSIM 7 and Aspen HYSYS results.  python examples/andreasen_stats.py <clone> <rerun.json>"""
import sys, json
import numpy as np
clone, f = sys.argv[1], sys.argv[2]
ref = np.loadtxt(f"{clone}/data/DWSIM_result.csv", delimiter=","); hys = np.loadtxt(f"{clone}/data/HYSYS_result.csv", delimiter=",")
out = np.array(json.load(open(f)), dtype=float)            # rows: solved, crude flow (kmol/h), power (kW), RVP (psi)
n = len(out); ok = out[:, 0] == 1
print(f"cases {n}, solved {int(ok.sum())}")
names = ["crude flow", "power", "RVP"]
for j, name in enumerate(names):
    mine = out[ok, j + 1]
    for lab, other in (("paper DWSIM 7", ref[:n][ok, j]), ("paper HYSYS", hys[:n][ok, j] if hys.shape[1] > j else None)):
        if other is None: continue
        rel = (mine - other) / other * 100
        print(f"{name:11} vs {lab:14}: mean {rel.mean():+.3f}%  MAE {np.abs(rel).mean():.3f}%  max |{np.abs(rel).max():.2f}|%  r = {np.corrcoef(mine, other)[0, 1]:.5f}")
for j, name in enumerate(names):
    rel = (ref[:n][ok, j] - hys[:n][ok, j]) / hys[:n][ok, j] * 100
    print(f"(for scale) paper DWSIM 7 vs paper HYSYS, {name}: MAE {np.abs(rel).mean():.3f}%  max {np.abs(rel).max():.2f}%")
