import copy, json, os, unittest
from hysys_bridge import mcp_server as M
from hysys_bridge.casebook import hazop, hazop_rules as R, tools
from hysys_bridge.tests.test_hazop import hx, spec, sim

STORE = R.load()


class Store(unittest.TestCase):
    def test_store_validates_and_every_entry_cites_a_read_source(self):
        self.assertEqual(R.validate(STORE), [])
        ids = {s["id"] for s in STORE["sources"]}; self.assertEqual(ids, {"safeche-hazop-tutorial", "nptel-iitm-lecture-13"})
        for s in STORE["sources"]: self.assertTrue(s["how_read"]); self.assertTrue(s["read"]); self.assertTrue(s["url"].startswith("https://"))
        self.assertIn("Wayback", next(s for s in STORE["sources"] if s["id"] == "safeche-hazop-tutorial")["how_read"])      # the live page answered a bot challenge; that is recorded
        for kind in ("causes", "safeguard_types", "worked_examples", "method_notes"):
            for e in STORE[kind]: self.assertTrue(set(e["sources"]) <= ids, e["id"])

    def test_every_entry_is_an_unreviewed_candidate(self):
        for e in STORE["causes"] + STORE["safeguard_types"]: self.assertEqual(e["status"], "candidate-unreviewed")
        self.assertIn("never a finding", " ".join(R.validate({**STORE, "causes": [{**STORE["causes"][0], "status": "accepted"}]})))

    def test_validation_rules_fire(self):
        def bad(mut):
            s = copy.deepcopy(STORE); mut(s); return " | ".join(R.validate(s))
        self.assertIn("sources must name read sources", bad(lambda s: s["causes"][0].update(sources=["invented"])))
        self.assertIn("sources must name read sources", bad(lambda s: s["causes"][0].update(sources=[])))
        self.assertIn("unknown guide word", bad(lambda s: s["causes"][0].update(guide_word="SOMETIMES")))
        self.assertIn("equipment must be one of", bad(lambda s: s["causes"][0].update(equipment="reactor")))
        self.assertIn("text is required", bad(lambda s: s["causes"][0].update(text=" ")))
        self.assertIn("id missing or duplicated", bad(lambda s: s["causes"][1].update(id=s["causes"][0]["id"])))
        self.assertIn("how_read is required", bad(lambda s: s["sources"][0].pop("how_read")))
        self.assertIn("responses_in_source must be", bad(lambda s: s["worked_examples"][0].update(responses_in_source=[])))
        self.assertIn("parameter is required", bad(lambda s: s["causes"][0].update(parameter="")))
        self.assertIn("text is required", bad(lambda s: s["method_notes"][0].pop("text")))

    def test_table_2_causes_are_all_present_by_deviation(self):
        want = {("flow", "NONE"): 4, ("flow", "LESS"): 3, ("flow", "MORE"): 3, ("flow", "REVERSE"): 3, ("pressure", "MORE"): 4, ("pressure", "LESS"): 1, ("temperature", "MORE"): 2, ("temperature", "LESS"): 2,
                ("level", "MORE"): 2, ("level", "LESS"): 2, ("composition", "OTHER_THAN"): 4}
        got = {}
        for c in STORE["causes"]: got[(c["parameter"], c["guide_word"])] = got.get((c["parameter"], c["guide_word"]), 0) + 1
        self.assertEqual(got, want); self.assertEqual(len(STORE["causes"]), 30)


class Suggest(unittest.TestCase):
    def texts(self, *a, **k): return [c["text"] for c in R.suggest(STORE, *a, **k)["causes"]]
    def test_exact_suggestions(self):
        self.assertEqual(self.texts("flow", "NONE"), ["valve closed", "pump failure", "incorrect pressure difference", "major leakage"])
        self.assertEqual(self.texts("temperature", "LESS"), ["loss of heating", "fouled exchanger"])
        self.assertEqual(self.texts("pressure", "LESS"), ["pump or compressor failure"])

    def test_upstream_equipment_filter_keeps_line_and_process_causes(self):
        self.assertEqual(self.texts("flow", "NONE", ["pump"]), ["pump failure", "incorrect pressure difference", "major leakage"])
        self.assertEqual(self.texts("flow", "NONE", []), ["incorrect pressure difference", "major leakage"])
        self.assertEqual(self.texts("flow", "MORE", ["valve", "pump"]), self.texts("flow", "MORE"))

    def test_composition_other_than_is_offered_for_both_composition_guide_words(self):
        a, b = self.texts("composition", "AS_WELL_AS"), self.texts("composition", "PART_OF"); self.assertEqual(a, b); self.assertEqual(len(a), 4)
        self.assertEqual(self.texts("flow", "AS_WELL_AS"), [])                                                       # the mapping applies to composition only

    def test_unsupported_or_unknown_combinations_return_nothing_not_a_guess(self):
        self.assertEqual(self.texts("temperature", "NONE"), []); self.assertEqual(self.texts("viscosity", "MORE"), [])
        s = R.suggest(STORE, "temperature", "NONE"); self.assertEqual((s["causes"], s["worked_examples"]), ([], []))

    def test_safeguard_types_and_worked_examples(self):
        names = lambda p, g: [x["text"] for x in R.suggest(STORE, p, g)["safeguard_types"]]
        self.assertEqual(names("flow", "NONE"), ["process alarms", "standard operating procedures"]); self.assertIn("pressure safety valves", names("pressure", "MORE"))
        ex = R.suggest(STORE, "flow", "NONE")["worked_examples"]; self.assertEqual(len(ex), 3)
        cool = next(e for e in ex if "cooled" in e["context"]); self.assertIn("control valve fails closed", cool["causes"]); self.assertIn("select a valve that fails open", cool["responses_in_source"]); self.assertIn("loss of cooling", cool["consequence"])
        self.assertEqual(len(R.suggest(STORE, "flow", "REVERSE")["worked_examples"]), 1)


class Runner(unittest.TestCase):
    ok = staticmethod(lambda c, p: {"ran": True, "solved": True, "sim": sim(), "findings": []})
    def test_suggestions_ride_beside_the_teams_fields_and_never_replace_them(self):
        s = spec(); s["nodes"][0]["deviations"][0].update(cause="team cause", safeguards=["team safeguard"]); ws = hazop.run_study(s, hx(), solve=self.ok); r = ws["rows"][0]
        self.assertEqual((r["cause"], r["safeguards"]), ("team cause", ["team safeguard"])); self.assertEqual([c["text"] for c in r["suggested"]["causes"]], ["valve fully open", "increased pump speed", "increased pressure difference"])
        md = hazop.render_markdown(ws); self.assertIn("team cause", md); self.assertIn("valve fully open", md); self.assertIn("Sources of the suggestions", md); self.assertIn("none reviewed", md); self.assertIn("Wayback", md)
        self.assertIn("Method note: Consequences are written assuming the existing safeguards are not working.", md)

    def test_upstream_equipment_limits_the_suggestions(self):
        s = spec(); s["nodes"][0]["upstream_equipment"] = ["pump"]
        self.assertEqual([c["text"] for c in hazop.run_study(s, hx(), solve=self.ok)["rows"][0]["suggested"]["causes"]], ["increased pump speed", "increased pressure difference"])
        s["nodes"][0]["upstream_equipment"] = ["reactor"]; self.assertTrue(any("upstream_equipment must be" in x for x in hazop.validate_spec(s, hx())))

    def test_suggestions_can_be_switched_off_and_reverse_still_gets_them(self):
        s = spec(suggestions=False); ws = hazop.run_study(s, hx(), solve=self.ok); self.assertIsNone(ws["rows"][0]["suggested"]); self.assertIsNone(ws["rules"]); self.assertNotIn("Sources of the suggestions", hazop.render_markdown(ws))
        s = spec(); s["nodes"][0]["deviations"] = [{"id": "rev", "parameter": "flow", "guide_word": "REVERSE"}]
        r = hazop.run_study(s, hx(), solve=self.ok)["rows"][0]; self.assertIs(r["evaluable"], False); self.assertEqual(len(r["suggested"]["causes"]), 3)

    def test_an_invalid_store_stops_the_study(self):
        bad = copy.deepcopy(STORE); bad["causes"][0]["sources"] = ["invented"]
        with self.assertRaisesRegex(ValueError, "rules store is not valid"): hazop.run_study(spec(), hx(), solve=self.ok, rules=bad)


class Tool(unittest.TestCase):
    def test_lookup_tool(self):
        self.assertIn("casebook_hazop_rules", M.TOOLS); h = M.TOOLS["casebook_hazop_rules"][0]
        self.assertEqual(h({})["counts"], {"causes": 30, "safeguard_types": 3, "worked_examples": 10, "method_notes": 5})
        out = h({"parameter": "flow", "guide_word": "NONE", "upstream_equipment": ["pump"]}); self.assertEqual([c["text"] for c in out["suggestions"]["causes"]], ["pump failure", "incorrect pressure difference", "major leakage"]); self.assertIn("none reviewed", out["status"])
        with self.assertRaises(ValueError): h({"parameter": "flow", "guide_word": "SOMETIMES"})


if __name__ == "__main__": unittest.main()
