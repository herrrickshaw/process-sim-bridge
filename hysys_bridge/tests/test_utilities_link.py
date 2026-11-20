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

    def test_minimum_separation_work_against_the_closed_form(self):
        from hysys_bridge import utilities_link as U
        x = U.X_N2_AIR; T = 298.15
        w, w_nm3, n_p = U.min_separation_work(1.0, 1.0, T)                                   # pure N2, all of it recovered: -RT sum x ln x per mol of air
        self.assertAlmostEqual(w, -U.R_GAS * T * (x * math.log(x) + (1 - x) * math.log(1 - x)), places=6); self.assertAlmostEqual(n_p, x)
        self.assertAlmostEqual(w_nm3, w / x * U.NM3_MOL)
        self.assertGreater(U.min_separation_work(0.999, 0.5)[1], 0)
        w_hi = U.min_separation_work(0.999, 0.95)[1]; self.assertGreater(w_hi, U.min_separation_work(0.99, 0.95)[1])      # purer product costs more
        for bad in ((0.5, 0.9), (1.0, 0.0), (0.99, 1.5)):
            with self.assertRaises(ValueError): U.min_separation_work(*bad)

    @unittest.skipUnless(HAVE, "needs CoolProp")
    def test_nitrogen_generation_routes(self):
        base = dict(product_nm3_h=1000.0, purity=0.995, delivery_P_kPa=800.0)
        err, p = call("utility_nitrogen_generation", method="psa", n2_recovery=0.45, feed_P_kPa=800.0, **base); self.assertFalse(err, p)
        self.assertAlmostEqual(p["feed_air_nm3_h"], 1000.0 * 0.995 / (0.45 * 0.7808)); self.assertAlmostEqual(p["waste_nm3_h"], p["feed_air_nm3_h"] - 1000.0)
        self.assertAlmostEqual(p["electric_kW"], sum(x["shaft_power_kW"] for x in p["stages"])); self.assertGreater(p["electric_kW"], p["min_work_kW"])
        self.assertLess(p["implied_second_law_eff"], 1.0)
        c = call("utility_nitrogen_generation", method="cryogenic", **base)[1]; self.assertIn("second_law_eff", c["assumed_defaults"])
        self.assertAlmostEqual(c["electric_kW"], c["min_work_kW"] / 0.25 + c["stages"][0]["shaft_power_kW"])
        hi = call("utility_nitrogen_generation", method="psa", n2_recovery=0.3, feed_P_kPa=800.0, **base)[1]; self.assertGreater(hi["electric_kW"], p["electric_kW"])   # lower recovery, more feed air
        self.assertTrue(call("utility_nitrogen_generation", method="psa", feed_P_kPa=800.0, **base)[0])               # PSA recovery is vendor data: required, not defaulted
        for bad in (dict(method="cryogenic", purity=0.5), dict(method="cryogenic", n2_recovery=1.5), dict(method="distillation")):
            self.assertTrue(call("utility_nitrogen_generation", **{**base, **bad})[0])

    @unittest.skipUnless(HAVE, "needs CoolProp")
    def test_balance_uses_generation_when_asked(self):
        err, r = call("utilities_balance", n2_nm3_h=1000.0, n2_P_out_kPa=800.0, n2_method="psa", n2_purity=0.995, n2_recovery=0.45, n2_feed_P_kPa=800.0); self.assertFalse(err, r)
        self.assertAlmostEqual(r["summary"]["compressor_shaft_kW"], r["nitrogen"]["electric_kW"]); self.assertAlmostEqual(r["summary"]["cooling_duty_kW"], r["nitrogen"]["cooling_duty_kW"])
        self.assertEqual(r["nitrogen"]["method"], "psa")


@unittest.skipUnless(HAVE, "needs CoolProp")
class Boiler(unittest.TestCase):
    def test_heating_values_match_the_known_lhv(self):
        from hysys_bridge import utilities_link as U
        for fuel, mj in (("methane", 50.0), ("ethane", 47.5), ("propane", 46.35), ("hydrogen", 120.0)):
            self.assertAlmostEqual(U.fuel_lhv_kj_mol(fuel) / U.FUELS[fuel]["M"], mj, delta=0.01 * mj)

    def test_energy_balance_and_combustion_closure(self):
        err, r = call("utility_boiler", steam_kg_h=10000.0, steam_P_kPa=1000.0, feedwater_T_C=105.0, blowdown_pct=2.0); self.assertFalse(err, r)
        q = (10000.0 * (r["steam_h_kJ_kg"] - r["feedwater_h_kJ_kg"])) / 3600 + 200.0 * (CoolProp.CoolProp.PropsSI("H", "P", 1e6, "Q", 0, "Water") / 1e3 - r["feedwater_h_kJ_kg"]) / 3600
        self.assertAlmostEqual(r["heat_to_water_kW"], q, places=6); self.assertAlmostEqual(r["feedwater_kg_h"], 10200.0)
        self.assertAlmostEqual(r["fuel_kW_lhv"] * r["efficiency_lhv"], r["heat_to_water_kW"])
        self.assertAlmostEqual(r["fuel_kg_h"] * r["fuel_lhv_kJ_kg"] / 3600, r["fuel_kW_lhv"], delta=1e-6 * r["fuel_kW_lhv"])
        self.assertAlmostEqual(r["co2_kg_h"], r["fuel_kg_h"] / 16.043 * 44.01, delta=1e-4 * r["co2_kg_h"])                # 1 mol CO2 per mol CH4
        c = r["combustion"]; self.assertAlmostEqual(c["flue_gas_mol_per_mol_fuel"]["Water"], 2.0)
        self.assertAlmostEqual(c["flue_gas_mol_per_mol_fuel"]["Oxygen"], 2.0 * 0.15)                                      # excess O2 = 15% of the 2 mol needed
        self.assertAlmostEqual(c["flue_gas_O2_dry_pct"], 3.0, delta=0.2); self.assertTrue(0.85 < r["efficiency_lhv"] < 0.95)
        self.assertEqual(set(r["assumed_defaults"]), {"ambient_T_C", "excess_air_pct", "stack_T_C", "radiation_loss_frac"})        # feedwater T and blowdown were given

    def test_losses_move_the_right_way(self):
        base = dict(steam_kg_h=10000.0, steam_P_kPa=1000.0)
        e = lambda **k: call("utility_boiler", **base, **k)[1]["efficiency_lhv"]
        self.assertGreater(e(stack_T_C=140.0), e(stack_T_C=250.0)); self.assertGreater(e(excess_air_pct=5.0), e(excess_air_pct=40.0))
        self.assertAlmostEqual(e(stack_T_C=25.0, radiation_loss_frac=0.0), 1.0, places=9)                                 # no flue-gas heat to lose when it leaves at ambient
        self.assertAlmostEqual(call("utility_boiler", efficiency_lhv=0.9, **base)[1]["efficiency_lhv"], 0.9)
        self.assertEqual(call("utility_boiler", efficiency_lhv=0.9, **base)[1]["efficiency_basis"], "given")
        h2 = call("utility_boiler", fuel="hydrogen", **base)[1]; self.assertEqual(h2["co2_kg_h"], 0.0); self.assertLess(h2["fuel_kg_h"], call("utility_boiler", **base)[1]["fuel_kg_h"] / 2)
        self.assertTrue(any("dew point" in w for w in call("utility_boiler", stack_T_C=60.0, **base)[1]["warnings"]))
        for bad in (dict(fuel="coal"), dict(steam_T_C=100.0), dict(feedwater_T_C=300.0), dict(efficiency_lhv=1.5), dict(stack_T_C=10.0)):
            self.assertTrue(call("utility_boiler", **{**base, **bad})[0])

    def test_balance_with_a_boiler(self):
        err, r = call("utilities_balance", steam_duty_kW=10000.0, steam_P_kPa=1000.0, condensate_return_fraction=0.5, boiler_fuel="methane"); self.assertFalse(err, r)
        self.assertAlmostEqual(r["boiler"]["steam_kg_h"], r["steam"]["steam_kg_h"]); self.assertEqual(r["summary"]["boiler_fuel_kg_h"], r["boiler"]["fuel_kg_h"])
        self.assertAlmostEqual(r["boiler"]["blowdown_kg_h"], r["demin"]["boiler_blowdown_kg_h"])                           # one blowdown figure across boiler and demin
        self.assertTrue(call("utilities_balance", boiler_fuel="methane")[0])


if __name__ == "__main__":
    unittest.main()
