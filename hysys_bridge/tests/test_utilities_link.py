import json, math, unittest
from hysys_bridge import mcp_server as M
try: import CoolProp; HAVE = True
except ImportError: HAVE = False


def call(tool, **args):
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})["result"]
    t = r["content"][0]["text"]; return r["isError"], (t if r["isError"] else json.loads(t))


class Utilities(unittest.TestCase):
    def test_registered(self):
        names = {t["name"] for t in M.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertTrue({"utility_compressed_gas", "utility_cooling_water", "utility_demin_water", "utilities_balance"} <= names)

    def test_demin_mass_balance_is_pure_arithmetic(self):
        err, r = call("utility_demin_water", steam_kg_h=10000.0, condensate_return_fraction=0.6, boiler_steam_kg_h=50000.0, blowdown_pct=2.0, demin_recovery=0.8)
        self.assertAlmostEqual(r["condensate_lost_kg_h"], 4000.0); self.assertAlmostEqual(r["boiler_blowdown_kg_h"], 1000.0); self.assertAlmostEqual(r["demin_makeup_kg_h"], 5000.0)
        self.assertAlmostEqual(r["raw_water_to_demin_kg_h"], 6250.0); self.assertAlmostEqual(r["demin_reject_kg_h"], 1250.0); self.assertEqual(r["assumed_defaults"], {})
        err, d = call("utility_demin_water", steam_kg_h=10000.0, condensate_return_fraction=1.0); self.assertEqual(set(d["assumed_defaults"]), {"boiler_steam_kg_h", "blowdown_pct", "demin_recovery"})
        for bad in (dict(condensate_return_fraction=1.5), dict(steam_kg_h=-1.0)):
            self.assertTrue(call("utility_demin_water", **{"steam_kg_h": 1.0, "condensate_return_fraction": 0.5, **bad})[0])

    @unittest.skipUnless(HAVE, "needs CoolProp")
    def test_cooling_water_heat_balance_and_tower_salt_balance(self):
        err, r = call("utility_cooling_water", duty_kW=10000.0, supply_T_C=30.0, return_T_C=40.0, cooling_tower=True, cycles_of_concentration=5.0, evaporative_fraction=0.8)
        self.assertAlmostEqual(r["flow_kg_s"] * r["cp_kJ_kgK"] * 10.0, 10000.0)
        self.assertAlmostEqual(r["blowdown_kg_s"] + r["drift_kg_s"], r["evaporation_kg_s"] / 4.0, places=9)                # COC = makeup/(blowdown+drift) = 5
        self.assertAlmostEqual(r["makeup_kg_s"] / (r["blowdown_kg_s"] + r["drift_kg_s"]), 5.0, places=6)
        self.assertAlmostEqual(r["evaporation_kg_s"] * r["latent_heat_kJ_kg"], 0.8 * 10000.0)
        self.assertTrue(call("utility_cooling_water", duty_kW=1.0, supply_T_C=40.0, return_T_C=30.0)[0])

    @unittest.skipUnless(HAVE, "needs CoolProp")
    def test_compression_energy_and_intercooling(self):
        err, r = call("utility_compressed_gas", gas="air", nm3_h=1000.0, P_in_kPa=101.325, P_out_kPa=800.0); self.assertFalse(err, r)
        self.assertEqual(r["stages"], 2); self.assertAlmostEqual(r["stage_ratio"], (800 / 101.325) ** 0.5)
        self.assertAlmostEqual(r["shaft_power_kW"], r["gas_power_kW"] / 0.95)
        self.assertAlmostEqual(r["gas_power_kW"], sum(x["work_kJ_kg"] for x in r["stage_rows"]) * r["mass_kg_s"])
        k, R, T = 1.4, 287.05, 303.15; ratio = 800 / 101.325                                     # single-stage ideal-gas isentropic reference, no intercooling
        one = r["mass_kg_s"] * k / (k - 1) * R * T * (ratio ** ((k - 1) / k) - 1) / 1e3 / 0.75
        self.assertLess(r["gas_power_kW"], one); self.assertGreater(r["gas_power_kW"], 0.75 * one)                    # intercooling saves, but only ~10-20%
        # every cooler returns the gas to T_ic: heat removed = enthalpy drop, so cooling duty ~ gas power (the compressor heat goes to water)
        self.assertAlmostEqual(r["cooling_duty_kW"] / r["gas_power_kW"], 1.0, delta=0.05)
        self.assertEqual(call("utility_compressed_gas", gas="nitrogen", nm3_h=1000.0, P_in_kPa=101.325, P_out_kPa=300.0)[1]["stages"], 1)
        p = call("utility_compressed_gas", gas="air", nm3_h=900.0, P_in_kPa=101.325, P_out_kPa=800.0, dryer_purge_fraction=0.1)[1]
        self.assertAlmostEqual(p["compressed_nm3_h"], 1000.0); self.assertEqual(call("utility_compressed_gas", gas="argon", nm3_h=1.0, P_in_kPa=100.0, P_out_kPa=200.0)[0], True)
        self.assertTrue(call("utility_compressed_gas", gas="air", nm3_h=1.0, P_in_kPa=500.0, P_out_kPa=200.0)[0])

    @unittest.skipUnless(HAVE, "needs CoolProp")
    def test_balance_connects_the_systems(self):
        err, r = call("utilities_balance", steam_duty_kW=10000.0, steam_P_kPa=1000.0, condensate_return_fraction=0.5, air_nm3_h=2000.0, air_P_out_kPa=800.0,
                      n2_nm3_h=500.0, n2_P_out_kPa=1000.0, other_cooling_duty_kW=5000.0); self.assertFalse(err, r)
        sm = r["summary"]
        self.assertAlmostEqual(sm["cooling_duty_kW"], 5000.0 + r["air"]["cooling_duty_kW"] + r["nitrogen"]["cooling_duty_kW"])
        self.assertAlmostEqual(sm["compressor_shaft_kW"], r["air"]["shaft_power_kW"] + r["nitrogen"]["shaft_power_kW"])
        self.assertAlmostEqual(r["demin"]["condensate_lost_kg_h"], 0.5 * r["steam"]["steam_kg_h"])
        self.assertTrue(call("utilities_balance", air_nm3_h=100.0)[0])                                                  # header pressure missing
        self.assertTrue(call("utilities_balance", steam_duty_kW=1000.0, steam_P_kPa=1000.0)[0])                          # return fraction missing: not guessed


if __name__ == "__main__":
    unittest.main()
