import json, os, unittest

PATH = os.path.join(os.path.dirname(__file__), "..", "..", "studies", "answer_keys", "liu_sharma_polyolefin_tables.json")
D = json.load(open(PATH))


def digits(s): return len(s.split(".")[1]) if "." in s else 0


class PrintedTables(unittest.TestCase):
    """Arithmetic checks of tables printed in Liu and Sharma (CC BY 4.0, engrXiv). A listed slip is asserted as a slip, so a later fix of the data file or of the source shows up as a test change."""
    def test_attribution_and_licence_recorded(self):
        for k, s in D["sources"].items(): self.assertTrue(s["doi"].startswith("10.31224/")); self.assertIn("Creative Commons Attribution 4.0", s["licence"])
        self.assertIn("Attribution", D["about"])

    def test_percent_errors_follow_the_printed_formula_except_the_known_slips(self):
        bad = set()
        for t in D["error_tables"]:
            for name, target, sim, printed in t["rows"]:
                got = abs(target - sim) / target * 100
                if round(got, digits(printed)) != float(printed): bad.add(f'{t["id"].split()[0]} {name}')
        self.assertEqual(bad, {"T4.12 MWW", "T6.11 MWW g/mol"})
        eva = next(r for t in D["error_tables"] if t["id"] == "T4.12" for r in t["rows"] if r[0] == "MWW"); self.assertAlmostEqual(abs(eva[1] - eva[2]) / eva[1] * 100, 0.085, places=3)       # printed 0.0085: a decimal place lost
        sbs = next(r for t in D["error_tables"] if t["id"] == "T6.11" for r in t["rows"] if r[0] == "MWW g/mol"); self.assertAlmostEqual(abs(sbs[1] - sbs[2]) / sbs[1] * 100, 7.04, places=2)   # printed 6.96

    def test_pdi_is_mww_over_mwn_except_two_decimal_slips(self):
        bad = {}
        for t in D["pdi_tables"]:
            got = t["MWW"] / t["MWN"]
            if abs(got / float(t["PDI"]) - 1) > 1e-4: bad[t["id"]] = got                          # the inputs are themselves rounded, so a relative 1e-4 test, not last-digit equality
        self.assertEqual(set(bad), {"T5.13 D221OUT", "T5.15 SL2"})
        self.assertAlmostEqual(bad["T5.13 D221OUT"], 5.37154, places=4); self.assertAlmostEqual(bad["T5.15 SL2"], 5.71002, places=4)          # printed 53.7154 and 57.1002: a factor of ten
        for t in D["pdi_tables"]: self.assertGreaterEqual(t["MWW"] / t["MWN"], 1.0)

    def test_table_5_13_balances(self):
        t = D["table_5_13"]; tot, hdpe, c2 = t["total"], t["HDPE"], t["C2H4"]
        self.assertAlmostEqual(tot[1], tot[0], places=1)                                    # the first reactor conserves mass
        self.assertAlmostEqual(hdpe[4] / (c2[0] + c2[3]) * 100, 96.10, places=2)           # the printed conversion
        # reactor 1: ethylene consumed (5574.55) = HDPE formed (5374.93) + oligomer formed (202.31) less 2.7 kg/h (hydrogen taken up): closes within 0.1 percent
        used = c2[0] - c2[1]; made = hdpe[1] + (t["LP"][1] - t["LP"][0]); self.assertAlmostEqual(made / used, 1.0, delta=1e-3)
        # the Slurry total repeats the D201OUT total although its listed components are 26 kg/h lower; the D221OUT total less Feed2 gives the true slurry flow
        self.assertEqual(tot[2], tot[1]); lost = sum(t[k][1] - t[k][2] for k in ("C2H4", "C4H8", "HDPE", "LP", "HX")); self.assertAlmostEqual(lost, 26.3, delta=0.1)
        self.assertAlmostEqual(tot[4] - tot[3], 14618.8, places=1); self.assertAlmostEqual(tot[1] - (tot[4] - tot[3]), 27.5, places=1)
        # reactor 2: the selected components do not close: ethylene consumed exceeds HDPE and oligomer formed by about 98 kg/h (a reading, not a proven error: unlisted components exist)
        used2 = (c2[2] + c2[3]) - c2[4]; made2 = (hdpe[4] - hdpe[2]) + (t["LP"][4] - t["LP"][2] - t["LP"][3]); self.assertAlmostEqual(used2 - made2, 98.5, delta=1.0)

    def test_table_5_15_conversion_formula_has_a_digit_slip_but_the_result_is_right(self):
        t = D["table_5_15"]; right = t["HDPE_SL2"] / (t["feed_C2H4_in_table"] + t["feed2_C2H4_in_table"]) * 100; slip = t["HDPE_SL2"] / (5089.14 + t["feed2_C2H4_in_table"]) * 100
        self.assertAlmostEqual(right, 92.5, places=1); self.assertAlmostEqual(slip, 96.9, places=1)                          # the printed formula says 5089.14 where the table has 5589.14

    def test_table_5_20_pp_does_not_close_on_the_printed_numbers(self):
        feed, out_prop, pp = 29286.83, 5292.11, 28996.8
        self.assertAlmostEqual(pp - (feed - out_prop), 5002.1, places=1)                                                     # more PP than propene consumed (21 percent); the closed loop is 5411 above
        self.assertAlmostEqual(29210.7 - (feed - 5487.4), 5411.3, places=1)


if __name__ == "__main__": unittest.main()
