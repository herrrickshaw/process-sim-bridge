"""Run the DWSIM steam-cycle models and dump rows to JSON for crosscheck_steam_cycle.py.  python3 -m examples.dump_dwsim_rows [out.json]"""
import json, sys

from examples import doe_netl_b11a_steam_cycle as E
out = {}
r1 = E.run(E.condensate_train(), E.CONDENSATE)
r2 = E.run(E.boiler_section(), {"BFW": (*E.BOILER_IN[:2], E.BOILER_IN[2]), "MS": (*E.BOILER_OUT[:2], E.BOILER_OUT[2])})
out["condensate"] = [dict(zip(("stream","T_F","P_psia","H_report","H_dwsim_kJkg","T_C_dwsim","P_kPa_dwsim"), r)) for r in r1[0]]
out["boiler"] = [dict(zip(("stream","T_F","P_psia","H_report","H_dwsim_kJkg","T_C_dwsim","P_kPa_dwsim"), r)) for r in r2[0]]
out["W_cond"], out["W_boiler"] = E.W_COND, E.W_BOILER
json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "dwsim_rows.json","w"), indent=1); print("dumped")
