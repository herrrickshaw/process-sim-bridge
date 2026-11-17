import os, unittest, tempfile
from hysys_bridge import extract_hmb, normalize, validate, hysys_writer, hmb_check
from hysys_bridge.backend import MockHysys

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample", "hmb.csv")


def load():
    fs = extract_hmb.from_csv(SAMPLE); normalize.normalize(fs); return fs


class T(unittest.TestCase):
    def test_extract_units_and_provenance(self):
        fs = load()
        s1 = fs.streams["1"]
        self.assertAlmostEqual(s1.P_kPa, 200 + 101.325)           # barg -> kPa abs
        self.assertEqual(s1.kind, "feed")
        self.assertIn("r", s1.source["T"])
        self.assertEqual(fs.streams["4"].kind, "product")
        self.assertAlmostEqual(fs.streams["3"].composition["Ethanol"], 0.334)

    def test_ambiguous_pressure_unit_rejected(self):
        with self.assertRaises(ValueError):
            extract_hmb.from_rows([["Stream No.", "1"], ["Pressure", "2"]])

    def test_unknown_unit_rejected(self):
        with self.assertRaises(ValueError):
            extract_hmb.from_rows([["Stream No.", "1"], ["Pressure (furlong)", "2"]])

    def test_sample_validates_clean(self):
        self.assertEqual(validate.blocking(validate.validate(load())), [])

    def test_composition_sum_error(self):
        fs = load(); fs.streams["1"].composition["Water"] = 0.5
        self.assertTrue(any("composition" in i.msg for i in validate.blocking(validate.validate(fs))))

    def test_mass_balance_error(self):
        fs = load(); fs.streams["3"].mass_flow_kg_h = 1400
        self.assertTrue(any("mass balance" in i.msg for i in validate.validate(fs)))

    def test_implicit_mixer_inserted(self):
        rows = [["Stream No.", "1", "2", "3"], ["From", "-", "-", "P-1"], ["To", "P-1", "P-1", "-"]]
        fs = extract_hmb.from_rows(rows); log = normalize.normalize(fs)
        self.assertIn("MX-P-1", fs.units); self.assertTrue(log)
        self.assertEqual(sorted(fs.units["MX-P-1"].inlets), ["1", "2"])

    def test_writer_only_specs_and_readback_ok(self):
        fs = load(); be = MockHysys(); rows = hysys_writer.write(fs, be)
        self.assertTrue(all(r.status == "OK" for r in rows))
        props = {(r.stream, r.prop) for r in rows}
        self.assertNotIn(("3", "mass"), props)                    # intermediate not written
        self.assertIn(("4", "T"), props)                          # heater outlet spec derived

    def test_readback_catches_corruption(self):
        fs = load(); be = MockHysys(corrupt=lambda s, p, v: v * 1.0001 if p == "P" else v)
        rows = hysys_writer.write(fs, be)
        self.assertTrue(any(r.status == "MISMATCH" and r.prop == "P" for r in rows))

    def test_post_solve_check_flags_disagreement(self):
        fs = load(); be = MockHysys(calc={("3", "mass"): 1500.0, ("4", "T"): 80.0, ("3", "T"): 45.0})
        hysys_writer.write(fs, be)
        bad = [d for d in hmb_check.check(fs, be) if not d.ok and d.stream == "3" and d.prop == "T"]
        self.assertEqual(len(bad), 1)


if __name__ == "__main__":
    unittest.main()
