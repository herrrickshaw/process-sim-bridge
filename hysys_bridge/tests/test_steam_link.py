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

    @unittest.skipUnless(HAVE, "needs CoolProp")
    def test_reheat_extraction_sections_and_identities(self):
        base = dict(duty_kW=10000.0, reheat_P_kPa=4000.0, reheat_T_C=565.0)
        err, hp = call("steam_lost_power", extraction_P_kPa=6000.0, **base); self.assertFalse(err, hp)
        err, lp = call("steam_lost_power", extraction_P_kPa=1000.0, **base); self.assertFalse(err, lp)
        self.assertEqual(hp["extraction"]["section"], "HP/cold reheat"); self.assertEqual(lp["extraction"]["section"], "IP/LP")
        rh = hp["reheat"]; self.assertEqual(lp["reheat"]["reheater_heat_saved_kW"], 0.0)
        # HP extraction forgoes remaining HP work + all IP/LP work (independent re-sum from the reported section works)
        h_ext = hp["extraction"]["h_kJ_kg"]; h_crh = rh["cold_reheat_via_extraction_h_kJ_kg"]
        self.assertAlmostEqual(hp["work_still_available_kJ_kg"], (h_ext - h_crh) + rh["ip_lp_work_kJ_kg"], places=6)
        self.assertAlmostEqual(hp["reheat"]["reheater_heat_saved_kW"], hp["steam_kg_s"] * (rh["hot_reheat"]["h_kJ_kg"] - h_crh))
        self.assertGreater(hp["lost_power_per_heat_delivered"], lp["lost_power_per_heat_delivered"])      # skipping the reheat costs more power
        # at the cold-reheat pressure the HP-section answer is the whole IP/LP work (no HP work left)
        err, at = call("steam_lost_power", extraction_P_kPa=4000.0, **base); self.assertAlmostEqual(at["work_still_available_kJ_kg"], rh["ip_lp_work_kJ_kg"], places=6)
        for bad in (dict(reheat_P_kPa=4000.0), dict(reheat_T_C=565.0), dict(reheat_P_kPa=30000.0, reheat_T_C=565.0)):
            self.assertTrue(call("steam_lost_power", duty_kW=1.0, extraction_P_kPa=1000.0, **bad)[0])
        self.assertTrue(call("steam_lost_power", extraction_P_kPa=3800.0, **base)[0])                 # inside the reheater pressure drop

    @unittest.skipUnless(HAVE, "needs CoolProp")
    def test_feedwater_credit_identities(self):
        base = dict(duty_kW=10000.0, extraction_P_kPa=1000.0)
        g = call("steam_lost_power", **base)[1]; self.assertIsNone(g["feedwater_credit"]); self.assertAlmostEqual(g["gross_lost_power_kW"], g["lost_power_kW"])
        full = call("steam_lost_power", fwh_extraction_P_kPa=200.0, condensate_return_T_C=90.0, **base)[1]
        half = call("steam_lost_power", fwh_extraction_P_kPa=200.0, condensate_return_T_C=90.0, condensate_return_fraction=0.5, **base)[1]
        c = full["feedwater_credit"]
        self.assertAlmostEqual(full["lost_power_kW"], full["gross_lost_power_kW"] - c["credit_kW"])
        self.assertAlmostEqual(c["credit_kW"], c["heater_steam_displaced_kg_s"] * c["heater_steam_work_kJ_kg"])           # displaced steam keeps expanding
        self.assertAlmostEqual(c["heater_steam_displaced_kg_s"] * c["heater_heat_per_kg_kJ_kg"], full["steam_kg_s"] * c["heat_returned_kJ_per_kg_extracted"])
        self.assertAlmostEqual(half["feedwater_credit"]["credit_kW"], 0.5 * c["credit_kW"])                              # linear in the return fraction
        self.assertGreater(c["credit_kW"], 0); self.assertLess(c["credit_kW"], full["gross_lost_power_kW"])
        none = call("steam_lost_power", fwh_extraction_P_kPa=200.0, condensate_return_T_C=38.0, **base)[1]            # returns at hotwell temperature: nothing to credit
        self.assertAlmostEqual(none["feedwater_credit"]["credit_kW"], 0.0, delta=5.0)
        hotter = call("steam_lost_power", fwh_extraction_P_kPa=700.0, condensate_return_T_C=90.0, **base)[1]            # same heat, taken at a higher-pressure heater: more work saved
        self.assertGreater(hotter["feedwater_credit"]["credit_kW"], c["credit_kW"])
        self.assertTrue(any("within 5 K" in w for w in call("steam_lost_power", fwh_extraction_P_kPa=200.0, condensate_return_T_C=118.0, **base)[1]["warnings"]))
        for bad in (dict(fwh_extraction_P_kPa=200.0), dict(condensate_return_T_C=90.0), dict(fwh_extraction_P_kPa=200.0, condensate_return_T_C=90.0, condensate_return_fraction=1.5),
                    dict(fwh_extraction_P_kPa=1.0, condensate_return_T_C=90.0), dict(fwh_extraction_P_kPa=200.0, condensate_return_T_C=200.0)):
            self.assertTrue(call("steam_lost_power", **base, **bad)[0])

    @unittest.skipUnless(HAVE, "needs CoolProp")
    def test_feedwater_credit_with_reheat(self):
        rh = dict(duty_kW=10000.0, extraction_P_kPa=6000.0, reheat_P_kPa=4000.0, reheat_T_C=565.0)
        a = call("steam_lost_power", **rh)[1]; b = call("steam_lost_power", fwh_extraction_P_kPa=700.0, condensate_return_T_C=120.0, **rh)[1]
        self.assertAlmostEqual(a["gross_lost_power_kW"], b["gross_lost_power_kW"]); self.assertLess(b["lost_power_kW"], a["lost_power_kW"])
        self.assertTrue(call("steam_lost_power", fwh_extraction_P_kPa=3800.0, condensate_return_T_C=120.0, **rh)[0])     # inside the reheater drop


if __name__ == "__main__":
    unittest.main()
