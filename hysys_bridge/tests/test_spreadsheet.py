import os, unittest
from hysys_bridge import extract_hmb, normalize, spreadsheet as S, hysys_writer, hmb_check

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample", "hmb.csv")


def sample():
    fs = extract_hmb.from_csv(SAMPLE); normalize.normalize(fs); return fs


class Units(unittest.TestCase):
    def test_round_trip_all_units(self):
        for kind, opts in S.CONV.items():
            for u in opts:
                prop = "x[A]" if kind == "x" else kind
                v = 123.4; self.assertAlmostEqual(S.from_sheet(prop, S.to_sheet(prop, v, {**S.DEFAULT_UNITS, kind: u}), {**S.DEFAULT_UNITS, kind: u}), v)

    def test_specific_conversions(self):
        u = S.make_units({"T": "K", "P": "bar", "mass": "kg/s"})
        self.assertAlmostEqual(S.to_sheet("T", 25, u), 298.15); self.assertAlmostEqual(S.to_sheet("P", 301.325, u), 3.01325)
        self.assertAlmostEqual(S.to_sheet("mass", 3600, u), 1.0)
        with self.assertRaises(ValueError): S.make_units({"P": "psi"})


class Layout(unittest.TestCase):
    def test_rows_are_deterministic_and_complete(self):
        fs = sample(); a, b = S.build_layout(fs), S.build_layout(fs)
        self.assertEqual([i.key for i in a.inputs], [i.key for i in b.inputs])
        self.assertEqual([i.row for i in a.inputs], list(range(len(a.inputs))))
        keys = {i.key for i in a.inputs}
        self.assertIn("1|T", keys); self.assertIn("1|x[Water]", keys); self.assertIn("4|T", keys)      # heater outlet spec
        self.assertNotIn("3|mass", keys)                                                          # intermediate not written
        self.assertIn("3|vf", {i.key for i in a.outputs})
        self.assertIn("row,label", S.build_layout(fs).csv().replace("sheet,row,label", "row,label"))

    def test_mass_basis_composition_rejected(self):
        fs = sample(); fs.streams["1"].composition_basis = "mass"
        with self.assertRaises(ValueError): S.build_layout(fs)


class Link(unittest.TestCase):
    def run_case(self, units=None, **mock):
        fs = sample(); lay = S.build_layout(fs, units); case = S.MockSheetCase(lay, **mock); be = case.backend()
        rows = hysys_writer.write(fs, be); solved = be.solve()
        return fs, be, rows, solved

    def test_clean_write_readback_and_propagation(self):
        fs, be, rows, solved = self.run_case()
        self.assertTrue(solved); self.assertTrue(all(r.status == "OK" for r in rows))
        self.assertEqual([p for p in S.verify_propagation(fs, be) if not p.ok], [])
        self.assertEqual(be.inp.Cell(1, 0).CellValue, 25.0)                                      # 1|T in degC

    def test_declared_units_reach_the_sheet(self):
        fs, be, rows, _ = self.run_case({"T": "K", "mass": "kg/s"})
        row = next(i.row for i in be.layout.inputs if i.key == "1|T"); self.assertAlmostEqual(be.inp.Cell(1, row).CellValue, 298.15)
        self.assertEqual([p for p in S.verify_propagation(fs, be) if not p.ok], [])               # converts back consistently

    def test_unit_mismatch_in_hysys_is_caught(self):
        fs, be, rows, _ = self.run_case(unit_bug={"mass": 1 / 3600})                              # HYSYS links kg/s, we assumed kg/h
        bad = [p for p in S.verify_propagation(fs, be) if not p.ok]
        self.assertTrue(bad and all(p.prop == "mass" for p in bad)); self.assertIn("HYSYS reports", str(bad[0]))

    def test_unlinked_cell_is_caught(self):
        fs, be, rows, _ = self.run_case(unlinked={("2", "T"), ("1", "T")})
        bad = {(p.stream, p.prop) for p in S.verify_propagation(fs, be) if not p.ok}
        self.assertIn(("1", "T"), bad)

    def test_hmb_check_reads_calculated_values(self):
        fs, be, rows, _ = self.run_case()
        diffs = hmb_check.check(fs, be)
        t1 = next(d for d in diffs if d.stream == "1" and d.prop == "T"); self.assertTrue(t1.ok)
        t3 = next(d for d in diffs if d.stream == "3" and d.prop == "T"); self.assertFalse(t3.ok)   # mock computes nothing downstream

    def test_unknown_row_is_loud(self):
        fs = sample(); be = S.MockSheetCase(S.build_layout(fs)).backend()
        with self.assertRaises(KeyError): be.set("99", "T", 1.0)


if __name__ == "__main__":
    unittest.main()
