"""Re-run Andreasen's 100-case parametric study of an oil-and-gas separation plant through our DWSIM MCP client.

Source: A. Andreasen, "Evaluation of an open-source chemical process simulator using a plant wide oil and gas separation plant flowsheet model
as basis" (https://doi.org/10.3311/PPch.19678); supplementary repo https://github.com/andr1976/dwsim-paper (MIT licence). Files used from it, kept
OUTSIDE this repo: simulations/optimisation.dwxmz, data/scaled_testplan.csv (100 x 10 inputs), data/DWSIM_result.csv (paper's DWSIM 7 results),
data/HYSYS_result.csv (paper's Aspen HYSYS results).
The flowsheet is loaded in the DWSIM MCP container through a read-only mount; the paper's own objects and set-points are applied (it used DWSIM's
automation API on Windows; we use dwsim_unitop_set / dwsim_stream_set_conditions / dwsim_solve_run). Object names differ: the paper's "01", "21", "63"
are tags MSTR-01, MSTR-21, MSTR-63 here. The fourth output (vapour ratio) is not reproduced: the script text defining its denominator is cut off in the repo copy read.
Needs numpy. Usage: python -u examples/andreasen_rerun.py <path-to-dwsim-paper-clone> [n_cases] [out.json]
"""
import os, sys, json, time; sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from hysys_bridge.dwsim.backend import StdioTransport
SIM=sys.argv[1]
X=np.loadtxt(f"{SIM}/data/scaled_testplan.csv",delimiter=",")
REF=np.loadtxt(f"{SIM}/data/DWSIM_result.csv",delimiter=","); HYS=np.loadtxt(f"{SIM}/data/HYSYS_result.csv",delimiter=",")
N=int(sys.argv[2]) if len(sys.argv)>2 else 1
OUT=sys.argv[3] if len(sys.argv)>3 else "andreasen_rerun.json"
t=StdioTransport(["podman","run","-i","--rm","--network","none","-v",f"{SIM}/simulations:/data:ro","ghcr.io/danwbr/dwsim-mcp:latest","--stdio"])
def c(tool,**a):
    try: return t.call(tool,a)
    except Exception as e: return {"ERROR":str(e)[:300]}
fid=c("dwsim_flowsheet_load",filepath="/data/optimisation.dwxmz")["flowsheet_id"]
def setu(name,props):
    r=c("dwsim_unitop_set",flowsheet_id=fid,name=name,properties=props)
    if "ERROR" in r: print("  SET FAIL",name,props,r["ERROR"][:260])
    return r
def apply(x):
    sep1t,sep1p,sep2p,sep3t,sep3p,s1,s2,s3,boost,refrig=x[0]+273.15,(1.013+x[1])*1e5,(1.013+x[2])*1e5,x[3]+273.15,(1.013+x[4])*1e5,x[5]+273.15,x[6]+273.15,x[7]+273.15,(1.013+x[8])*1e5,x[9]+273.15
    r=c("dwsim_stream_set_conditions",flowsheet_id=fid,name="MSTR-01",pressure_Pa=sep1p)
    if "ERROR" in r: print("  SET FAIL stream 01",r["ERROR"][:200])
    setu("20-HA-01",{"OutletTemperature":sep1t}); setu("VALV-01",{"OutletPressure":sep2p+0.5e5}); setu("VALV-02",{"OutletPressure":sep3p+0.5e5})
    setu("20-HA-03",{"OutletTemperature":sep3t}); setu("23-HA-01",{"OutletTemperature":s1}); setu("23-HA-02",{"OutletTemperature":s2}); setu("23-HA-03",{"OutletTemperature":s3})
    setu("23-KA-01",{"CalcMode":"Delta_P","DeltaP":boost-sep1p+1.5e5}); setu("25-HA-02",{"OutletTemperature":refrig})
def outputs():
    r63=c("dwsim_stream_get_results",flowsheet_id=fid,name="MSTR-63"); r21=c("dwsim_stream_get_results",flowsheet_id=fid,name="MSTR-21")
    rvp=r63["pressure_Pa"]/1e5*14.5; crude=r21["molar_flow_mol_s"]*3.6
    pw=0.0; det={}
    for u in ("23-KA-01","23-KA-02","23-KA-03","27-KA-01","21-PA-01"):
        res=c("dwsim_unitop_get_results",flowsheet_id=fid,name=u).get("properties",{}); det[u]={k:v["value"] for k,v in res.items() if k in ("Power Required","Heat Duty","Power","Energy Flow","DeltaQ")}
        v=res.get("Power Required") or res.get("Power") or res.get("Energy Flow")
        pw+=float(v["value"]) if v else float("nan")
    return crude,pw,rvp,det
out=[]
for i in range(N):
    t0=time.time(); apply(X[i]); r=c("dwsim_solve_run",flowsheet_id=fid,timeout_s=300); ok=r.get("ok")
    if not ok: r=c("dwsim_solve_run",flowsheet_id=fid,timeout_s=300); ok=r.get("ok")
    crude,pw,rvp,det=outputs() if ok else (np.nan,np.nan,np.nan,{})
    out.append((ok,crude,pw,rvp))
    print(f"case {i}: solved={ok} ({time.time()-t0:.1f}s) crude {crude:.1f} (paper {REF[i,0]:.1f}) | power {pw:.0f} (paper {REF[i,1]:.0f}, HYSYS {HYS[i,1]:.0f}) | RVP {rvp:.3f} (paper {REF[i,2]:.3f}, HYSYS {HYS[i,2]:.3f})")
    json.dump(out,open(OUT,"w"))
    sys.stdout.flush()
json.dump(out,open(OUT,"w"))
t.close()
