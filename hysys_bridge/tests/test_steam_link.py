import json, unittest
from hysys_bridge import mcp_server as M, steam_link as SL
try: import CoolProp; HAVE = True
except ImportError: HAVE = False


def call(tool, **args):
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})["result"]
    t = r["content"][0]["text"]; return r["isError"], (t if r["isError"] else json.loads(t))


class Steam(unittest.TestCase):
    def test_registered_and_boiler_heat_constant(self):
        names = {t["name"] for t in M.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertIn("steam_demand_for_duty", names)
        self.assertAlmostEqual(SL.B11A_BOILER_MW, 1235.0, delta=5)          # 4,120,442 lb/h x (1494-471) Btu/lb

    def test_needs_a_duty(self):
        err, msg = call("steam_demand_for_duty", steam_P_kPa=1000); self.assertTrue(err); self.assertIn("duty_kW", msg)

    @unittest.skipUnless(HAVE, "needs CoolProp")
    def test_saturated_steam_latent_heat_balance(self):
        err, r = call("steam_demand_for_duty", duty_kW=10000.0, steam_P_kPa=1000.0); self.assertFalse(err, r)
        self.assertAlmostEqual(r["T_sat_C"], 179.9, delta=0.1); self.assertAlmostEqual(r["heat_given_kJ_kg"], 2014.6, delta=2)   # h_fg at 10 bar
        self.assertAlmostEqual(r["steam_kg_s"] * r["heat_given_kJ_kg"], 10000.0)
        err, sub = call("steam_demand_for_duty", duty_kW=10000.0, steam_P_kPa=1000.0, condensate_T_C=120); self.assertLess(sub["steam_kg_h"], r["steam_kg_h"])
        err, bad = call("steam_demand_for_duty", duty_kW=1.0, steam_P_kPa=1000.0, process_outlet_T_C=250.0)
        self.assertFalse(bad["feasible"]); self.assertIn("INFEASIBLE", bad["warnings"][0])
        self.assertTrue(call("steam_demand_for_duty", duty_kW=1.0, steam_P_kPa=1000.0, process_outlet_T_C=150.0)[1]["feasible"])
        self.assertTrue(call("steam_demand_for_duty", duty_kW=1.0, steam_P_kPa=1000.0, steam_T_C=100)[0])           # liquid, not steam
        self.assertTrue(call("steam_demand_for_duty", duty_kW=-1.0, steam_P_kPa=1000.0)[0])

    @unittest.skipUnless(HAVE, "needs CoolProp")
    def test_lost_power_energy_balance_and_limits(self):
        err, r = call("steam_lost_power", duty_kW=10000.0, extraction_P_kPa=1000.0); self.assertFalse(err, r)
        self.assertAlmostEqual(r["steam_kg_s"] * r["heat_given_kJ_kg"], 10000.0)
        self.assertAlmostEqual(r["lost_power_kW"], r["steam_kg_s"] * r["work_still_available_kJ_kg"])
        self.assertAlmostEqual(r["work_still_available_kJ_kg"], r["extraction"]["h_kJ_kg"] - r["exhaust"]["h_kJ_kg"])
        self.assertGreater(r["lost_power_per_heat_delivered"], 0); self.assertLess(r["lost_power_per_heat_delivered"], 0.6)
        err, hi = call("steam_lost_power", duty_kW=10000.0, extraction_P_kPa=3000.0)      # earlier extraction keeps more work in the steam
        self.assertGreater(hi["work_still_available_kJ_kg"], r["work_still_available_kJ_kg"])
        e1, e2 = call("steam_lost_power", duty_kW=1.0, extraction_P_kPa=1000.0, eta_s_remaining=1.0)[1], r
        self.assertGreater(e1["work_still_available_kJ_kg"], e2["work_still_available_kJ_kg"])    # better turbine, more work forgone
        for bad in (dict(extraction_P_kPa=1.0), dict(extraction_P_kPa=30000.0), dict(extraction_P_kPa=1000.0, eta_s_remaining=1.5)):
            self.assertTrue(call("steam_lost_power", duty_kW=1.0, **bad)[0])
        self.assertTrue(call("steam_lost_power", extraction_P_kPa=1000.0)[0])


if __name__ == "__main__":
    unittest.main()
