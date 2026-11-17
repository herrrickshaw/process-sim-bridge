import math, unittest
from valve_sizing import relief, control, pressure

class T(unittest.TestCase):
    def test_C_k14_is_356(self): self.assertAlmostEqual(relief.gas_C(1.4), 356, delta=1)
    def test_critical_ratio_k14(self): self.assertAlmostEqual(relief.critical_ratio(1.4), 0.5283, places=3)

    def test_levels_rules(self):
        self.assertAlmostEqual(pressure.levels(1000).relieving_gauge, 1100)
        self.assertAlmostEqual(pressure.levels(1000, scenario="multiple").relieving_gauge, 1160)
        self.assertAlmostEqual(pressure.levels(1000, scenario="fire").relieving_gauge, 1210)
        self.assertAlmostEqual(pressure.levels(1000, 900, "fire").relieving_gauge, 1110 - 0 + 0)  # 900+210
        self.assertAlmostEqual(pressure.levels(1000).hydrotest_min, 1300)
        with self.assertRaises(ValueError): pressure.levels(1000, 1010)
        pressure.levels(1000, 1050, "multiple", supplemental=True)

    def test_steam_hand_calc(self):
        r = relief.size_steam(45359.237, mawp=6894.757 - 101.325, kd=0.975)   # 100000 lb/h, P1 = 1.1*MAWP...
        P1 = r.detail["P1_psia"]
        self.assertAlmostEqual(r.required_in2, 100000 / (51.5 * P1 * 0.975), places=4)

    def test_liquid_hand_calc(self):
        # relieving dP = 100 psi exactly: mawp such that 1.1*mawp - 0 = 100 psi
        mawp = 100 / 1.1 / relief.PSI_PER_KPA
        r = relief.size_liquid(100 / 4.40286754, 1.0, mawp, viscosity_cP=1.0)
        self.assertAlmostEqual(r.required_in2, 0.405, delta=0.01)       # Kv~0.99 for water
        self.assertEqual(r.orifice, "G")   # 0.405 in2 > F (0.307)

    def test_viscous_needs_bigger_area(self):
        a = relief.size_liquid(20, 0.9, 1000, viscosity_cP=1).required_in2
        b = relief.size_liquid(20, 0.9, 1000, viscosity_cP=2000).required_in2
        self.assertGreater(b, a)

    def test_gas_critical_vs_subcritical(self):
        c = relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000)
        self.assertEqual(c.detail["regime"], "critical")
        s = relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, backpressure=900)
        self.assertEqual(s.detail["regime"], "subcritical")
        self.assertGreater(s.required_in2, c.required_in2)

    def test_gas_area_scales_with_flow(self):
        a = relief.size_gas(5000, 400, 28, 1.3, 1.0, 1000).required_in2
        b = relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000).required_in2
        self.assertAlmostEqual(b / a, 2.0, places=6)

    def test_oversize_flags_multiple_valves(self):
        r = relief.size_gas(5e6, 400, 28, 1.3, 1.0, 1000)
        self.assertIsNone(r.orifice); self.assertTrue(any("x T" in w for w in r.warnings))

    def test_fire(self):
        f = relief.fire_vapour_rate(50, 300)
        self.assertAlmostEqual(f["Q_kW"], 43.2 * 50 ** 0.82, places=6)

    def test_control_liquid_water(self):
        r = control.liquid(100, 5, 4, 1.0, 0.03, 220.6)
        self.assertAlmostEqual(r.kv, 100.0, delta=0.01); self.assertAlmostEqual(r.cv, 115.6, delta=0.05)
        self.assertFalse(r.choked)

    def test_control_liquid_choked(self):
        r = control.liquid(100, 10, 0.5, 1.0, 5.0, 220.6, FL=0.9)
        self.assertTrue(r.choked)

    def test_control_gas_choked_Y(self):
        r = control.gas(1000, 10, 1, 300, 29, 1.4, xT=0.7)
        self.assertTrue(r.choked)
        n = control.gas(1000, 10, 9, 300, 29, 1.4, xT=0.7)
        self.assertFalse(n.choked); self.assertGreater(n.kv, 0)

if __name__ == "__main__": unittest.main()
