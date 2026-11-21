import unittest
from hysys_bridge import mcp_server as M
from hysys_bridge import polymer_link as P
from hysys_bridge.polymer_link import _finish

MW = {"E2": 28.05, "VA": 86.09}          # the chapter's segment molar masses (g/mol)


class Chapter1(unittest.TestCase):
    """Numbers printed in Liu and Sharma (2023), Chapter 1: the worked chain example (section 1.1.2) and Table 1.2 (section 1.1.3)."""
    def test_toy_example_three_chains(self):
        s = P.chain_statistics({3: 1, 4: 1, 5: 1})
        self.assertEqual((s["ZMOM"], s["FMOM"], s["SMOM"]), (3, 12, 50)); self.assertAlmostEqual(s["DPN"], 4.0); self.assertAlmostEqual(s["DPW"], 4.17, places=2); self.assertAlmostEqual(s["PDI"], 1.04, places=2)

    def test_table_1_2_stream_initialisation(self):
        s = P.init_stream(1.0, {"E2": 0.6, "VA": 0.4}, MW, 20000, 90000)
        want = {"MWSEG": 51.266, "DPN": 390.12, "DPW": 1755.55, "PDI": 4.5, "ZMOM": 0.00005, "FMOM": 0.019506, "SMOM": 34.2438}
        for k, v in want.items(): self.assertAlmostEqual(s[k] / v, 1.0, delta=1e-5, msg=k)
        self.assertAlmostEqual(s["SFLOW"]["E2"], 0.011704, places=6); self.assertAlmostEqual(s["SFLOW"]["VA"], 0.007802, places=6)
        self.assertAlmostEqual(s["MWN"], 20000, delta=1e-6); self.assertAlmostEqual(s["MWW"], 90000, delta=1e-6)

    # Figure 1.20, the printed sensitivity table of workshop 1.1 (EVA80 flow in kg/h varied against 3600 kg/h of EVA50): MWN, MWW, PDI
    PRINTED = [(3.6, 19821.8, 10.3341, 0.0005213), (7.2, 19647.1, 20.6298, 0.00105001), (18, 19142.9, 51.2858, 0.00267911), (36, 18363.6, 101.625, 0.00553402),
               (72, 17000, 199.56, 0.0117388), (180, 14000, 473.041, 0.0337886), (360, 11000, 870.373, 0.0791248), (720, 8000, 1498.32, 0.18729),
               (1800, 5000, 2626.31, 0.525263), (2520, 4250, 3057.82, 0.719488), (3600, 3636.36, 3480.94, 0.957259)]

    def streams(self, eva50_second_moment_specified):
        b = P.init_stream(1.0, {"E2": 0.5, "VA": 0.5}, MW, 20000, 50000)
        if not eva50_second_moment_specified: b = _finish({"mass_kg_s": b["mass_kg_s"], "ZMOM": b["ZMOM"], "FMOM": b["FMOM"], "SMOM": 0.0, "SFLOW": b["SFLOW"]})
        return lambda m80: [P.init_stream(m80 / 3600, {"E2": 0.8, "VA": 0.2}, MW, 2000, 5000), b]

    def test_printed_mwn_is_the_exact_mixing_result(self):
        mk = self.streams(True)
        for m80, mwn, _, _ in self.PRINTED: self.assertAlmostEqual(P.mix(mk(m80))["MWN"] / mwn, 1.0, delta=1e-5, msg=m80)

    def test_printed_table_cannot_come_from_the_stated_inputs(self):
        """With both streams entered as the problem states (EVA50 MWW 50,000), the mixture's MWW is far above the printed values and PDI is above 1."""
        mk = self.streams(True)
        for m80, mwn, mww, pdi in self.PRINTED:
            m = P.mix(mk(m80)); self.assertGreaterEqual(m["PDI"], 1.0); self.assertGreater(m["MWW"], 5 * mww if m80 < 3000 else 3 * mww)
            self.assertLess(pdi, 1.0 if m80 > 2000 else 1.0)        # the printed PDI column is below 1 in every row: impossible by definition

    def test_printed_table_matches_an_eva50_with_no_second_moment(self):
        """The printed MWW and PDI follow from the same mixing arithmetic if EVA50 carries a zero second moment (its MWW not entered): within 0.01 percent, all 11 rows.
        This shows consistency with that explanation, not that it is what happened."""
        mk = self.streams(False)
        for m80, mwn, mww, pdi in self.PRINTED:
            m = P.mix(mk(m80)); self.assertAlmostEqual(m["MWW"] / mww, 1.0, delta=2e-4, msg=("MWW", m80)); self.assertAlmostEqual(m["PDI"] / pdi, 1.0, delta=2e-4, msg=("PDI", m80))


class Definitions(unittest.TestCase):
    def test_mixing_invariants(self):
        a = P.init_stream(2.0, {"E2": 0.7, "VA": 0.3}, MW, 5000, 12000); b = P.init_stream(3.0, {"E2": 0.4, "VA": 0.6}, MW, 30000, 80000); m = P.mix([a, b])
        self.assertAlmostEqual(m["mass_kg_s"], 5.0); self.assertGreaterEqual(m["PDI"], 1.0)
        for k in ("ZMOM", "FMOM", "SMOM"): self.assertAlmostEqual(m[k], a[k] + b[k])
        self.assertAlmostEqual(m["MWN"], 5.0 / (2 / 5000 + 3 / 30000))                                      # harmonic in mass fraction
        self.assertAlmostEqual(m["MWW"], m["SMOM"] / m["FMOM"] * m["MWSEG"])                                  # the segment-moment definition
        self.assertNotAlmostEqual(m["MWW"], (2 * 12000 + 3 * 80000) / 5.0, delta=100)                         # not the mass-weighted blend when segment compositions differ
        same = P.mix([P.init_stream(2.0, {"E2": 0.6, "VA": 0.4}, MW, 5000, 12000), P.init_stream(3.0, {"E2": 0.6, "VA": 0.4}, MW, 30000, 80000)])
        self.assertAlmostEqual(same["MWW"], (2 * 12000 + 3 * 80000) / 5.0, delta=1e-6 * same["MWW"])             # with equal segment composition it is the mass-weighted blend
        self.assertAlmostEqual(sum(m["SFRAC"].values()), 1.0)

    def test_mixing_a_stream_with_itself_changes_nothing(self):
        a = P.init_stream(1.0, {"E2": 0.6, "VA": 0.4}, MW, 20000, 90000); m = P.mix([a, a])
        for k in ("MWN", "MWW", "PDI", "MWSEG"): self.assertAlmostEqual(m[k], a[k], places=6)

    def test_refusals(self):
        with self.assertRaisesRegex(ValueError, "below MWN"): P.init_stream(1.0, {"E2": 0.6, "VA": 0.4}, MW, 20000, 19999)
        with self.assertRaisesRegex(ValueError, "sum to"): P.init_stream(1.0, {"E2": 0.6, "VA": 0.3}, MW, 20000, 90000)
        with self.assertRaisesRegex(ValueError, "sum to"): P.init_stream(1.0, {"E2": 0.6, "VA": 0.399}, MW, 20000, 90000)        # 0.1 percent off is refused
        P.init_stream(1.0, {"E2": 0.6, "VA": 0.4000000001}, MW, 20000, 90000)                                             # rounding noise is accepted
        with self.assertRaisesRegex(ValueError, "exactly one"): P.init_stream(1.0, {"E2": 0.6, "VA": 0.4}, MW, 20000)
        with self.assertRaisesRegex(ValueError, "same segments"): P.init_stream(1.0, {"E2": 0.6, "VA": 0.4}, {"E2": 28.05}, 20000, 90000)
        with self.assertRaisesRegex(ValueError, "positive"): P.init_stream(0.0, {"E2": 0.6, "VA": 0.4}, MW, 20000, 90000)
        with self.assertRaisesRegex(ValueError, "second moment too small"): P.init_stream(1.0, {"E2": 0.6, "VA": 0.4}, MW, 20000, smom_kmol_s=1e-9)
        with self.assertRaisesRegex(ValueError, "at least two"): P.mix([P.init_stream(1.0, {"E2": 0.6, "VA": 0.4}, MW, 20000, 90000)])
        with self.assertRaisesRegex(ValueError, "positive chain"): P.chain_statistics({0: 1})

    def test_chain_statistics_single_length_has_pdi_one(self):
        self.assertAlmostEqual(P.chain_statistics({7: 2.5})["PDI"], 1.0)


class Tools(unittest.TestCase):
    def test_registered_and_callable(self):
        self.assertIn("polymer_mix", M.TOOLS); self.assertIn("polymer_stream_attributes", M.TOOLS)
        a = {"mass_kg_s": 1.0, "seg_mole_fractions": {"E2": 0.6, "VA": 0.4}, "seg_mw_kg_kmol": MW, "mwn": 20000, "mww": 90000}
        out = M.TOOLS["polymer_stream_attributes"][0](a); self.assertAlmostEqual(out["PDI"], 4.5)
        mixed = M.TOOLS["polymer_mix"][0]({"streams": [a, {**a, "mass_kg_s": 2.0, "mwn": 5000, "mww": 12000}]}); self.assertGreaterEqual(mixed["PDI"], 1.0); self.assertEqual(len(mixed["inputs"]), 2)
        with self.assertRaisesRegex(ValueError, "seg_mole_fractions is required"): M.TOOLS["polymer_mix"][0]({"streams": [{"mass_kg_s": 1.0}]})
        with self.assertRaisesRegex(ValueError, "mwn is required"): M.TOOLS["polymer_mix"][0]({"streams": [{k: v for k, v in a.items() if k != "mwn"}] * 2})


if __name__ == "__main__": unittest.main()
