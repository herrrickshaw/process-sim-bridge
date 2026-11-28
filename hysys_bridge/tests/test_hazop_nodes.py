import copy, glob, json, os, tempfile, unittest
from unittest import mock
from hysys_bridge import mcp_server as M
from hysys_bridge.ir import Flowsheet, Stream, Unit
from hysys_bridge.casebook import hazop, hazop_nodes as N, schema, tools
from hysys_bridge.tests.test_casebook import CASE
from hysys_bridge.tests.test_hazop import sim

CASES = os.path.dirname(CASE)
SIZES = {"reason": "site HAZOP procedure test table", "flow": {"MORE": {"relative": 0.2}, "LESS": {"relative": 0.2}}, "temperature": {"MORE": {"absolute": 10}, "LESS": {"absolute": 10}}, "pressure": {"MORE": {"relative": 0.1}, "LESS": {"relative": 0.1}}}


def graph(units, streams, origin="test"):
    return {"name": "g", "origin": origin, "units": {u: {"type": t, "flags": list(f)} for u, t, f in units}, "streams": {s: {"role": r, "src": a, "dst": b} for s, r, a, b in streams}}


def line_graph(flags=()):
    """F -> P (pump) -> V (valve) -> H (heater) -> SEP, two products; a second feed G -> M joins nothing else."""
    return graph([("P", "pump", flags), ("V", "valve", flags), ("H", "heater", flags), ("SEP", "separator", flags)],
                 [("F", "feed", None, "P"), ("S1", "intermediate", "P", "V"), ("S2", "intermediate", "V", "H"), ("S3", "intermediate", "H", "SEP"), ("VAP", "product", "SEP", None), ("LIQ", "product", "SEP", None)])


class Derive(unittest.TestCase):
    def test_line_equipment_chain_and_tags(self):
        d = N.derive(line_graph(), None, "s")["nodes"][0]
        self.assertEqual(d["line_units"], ["P", "V", "H"]); self.assertEqual(d["upstream_equipment"], ["heater", "pump", "valve"]); self.assertIn("F -> P (pump) -> V (valve) -> H (heater)", d["description"])

    def test_chain_stops_at_a_unit_with_two_inlets_or_outlets(self):
        g = graph([("P", "pump", []), ("M", "mixer", []), ("V", "valve", [])], [("F", "feed", None, "P"), ("G", "feed", None, "M"), ("S1", "intermediate", "P", "M"), ("S2", "intermediate", "M", "V"), ("OUT", "product", "V", None)])
        nodes = {n["stream"]: n for n in N.derive(g, None, "s")["nodes"]}
        self.assertEqual(nodes["F"]["line_units"], ["P", "M"]); self.assertEqual(nodes["F"]["upstream_equipment"], ["pump"]); self.assertEqual(nodes["G"]["line_units"], ["M"]); self.assertEqual(nodes["G"]["upstream_equipment"], [])

    def test_chain_stops_at_a_line_unit_with_two_inlets_or_two_outlets(self):
        two_in = graph([("P", "pump", []), ("V", "valve", []), ("H", "heater", [])], [("F", "feed", None, "P"), ("G", "feed", None, "V"), ("S1", "intermediate", "P", "V"), ("S2", "intermediate", "V", "H"), ("OUT", "product", "H", None)])
        self.assertEqual({n["stream"]: n["line_units"] for n in N.derive(two_in, None, "s")["nodes"]}, {"F": ["P", "V"], "G": ["V"]})        # V has two inlets: the chain ends there, V is the first process unit
        two_out = graph([("P", "pump", []), ("V", "valve", []), ("H", "heater", [])], [("F", "feed", None, "P"), ("S1", "intermediate", "P", "V"), ("S2", "intermediate", "V", "H"), ("S3", "intermediate", "V", "H"), ("OUT", "product", "H", None)])
        self.assertEqual(N.derive(two_out, None, "s")["nodes"][0]["line_units"], ["P", "V"])                                                  # V has two outlets: H is not on the line

    def test_exposure_reaches_downstream_units_only(self):
        u = N.derive(line_graph(), None, "s")["derivation"]["units"]
        for x in ("P", "V", "H", "SEP"): self.assertEqual(u[x]["reached_by_feeds"], ["F"])
        g = graph([("A", "heater", []), ("B", "cooler", [])], [("F", "feed", None, "A"), ("G", "feed", None, "B"), ("S", "intermediate", "A", "B"), ("OUT", "product", "B", None)])
        u = N.derive(g, None, "s")["derivation"]["units"]; self.assertEqual(u["A"]["reached_by_feeds"], ["F"]); self.assertEqual(u["B"]["reached_by_feeds"], ["F", "G"])

    def test_recycle_units_are_marked(self):
        g = graph([("M", "mixer", []), ("H", "heater", []), ("SP", "splitter", [])], [("F", "feed", None, "M"), ("S1", "intermediate", "M", "H"), ("S2", "intermediate", "H", "SP"), ("R", "intermediate", "SP", "M"), ("OUT", "product", "SP", None)])
        d = N.derive(g, None, "s")["derivation"]; self.assertTrue(all(d["units"][x]["in_recycle"] for x in ("M", "H", "SP"))); self.assertTrue(any("recycle loops" in w for w in d["warnings"]))
        self.assertFalse(any(x["in_recycle"] for x in N.derive(line_graph(), None, "s")["derivation"]["units"].values()))

    def test_standard_deviation_set_and_ids(self):
        devs = N.derive(graph([("U", "heater", [])], [("HOT_IN", "feed", None, "U"), ("OUT", "product", "U", None)]), None, "s")["nodes"][0]["deviations"]
        self.assertEqual([(d["parameter"], d["guide_word"]) for d in devs], [("flow", "NONE"), ("flow", "MORE"), ("flow", "LESS"), ("flow", "REVERSE"), ("temperature", "MORE"), ("temperature", "LESS"), ("pressure", "MORE"), ("pressure", "LESS")])
        self.assertEqual(devs[0]["id"], "hot-in-flow-none"); self.assertEqual(len({d["id"] for d in devs}), 8)
        self.assertFalse([d for d in devs if d["parameter"] == "composition"])                                    # composition needs a named compound: not proposed

    def test_watch_is_on_product_streams(self):
        w = N.derive(line_graph(), None, "s")["watch"]; self.assertEqual({x["stream"] for x in w}, {"VAP", "LIQ"}); self.assertEqual({x["property"] for x in w}, {"T", "mass", "vapor_fraction"})


class Sizes(unittest.TestCase):
    def test_no_sizes_means_no_size_and_the_draft_does_not_validate(self):
        c = schema.load(os.path.join(CASES, "water-counter-current-exchanger-tutorial.json")); d = N.derive(N.graph_from_case(c), c, "s")
        devs = [x for n in d["nodes"] for x in n["deviations"]]; sized = [x for x in devs if x["guide_word"] in ("MORE", "LESS")]
        self.assertTrue(sized and all(x["size"] is None and "needs" in x for x in sized)); self.assertEqual(len(d["derivation"]["missing_sizes"]), len(sized)); self.assertFalse(d["derivation"]["complete"])
        self.assertTrue(hazop.validate_spec(d, c))                                                                  # missing sizes are refused by the runner's validator
        for x in devs:
            if x["guide_word"] in ("NONE", "REVERSE"): self.assertNotIn("size", x)

    def test_supplied_sizes_carry_their_reason_and_make_a_runnable_spec(self):
        c = schema.load(os.path.join(CASES, "water-counter-current-exchanger-tutorial.json")); d = N.derive(N.graph_from_case(c), c, "s", SIZES)
        self.assertEqual(hazop.validate_spec(d, c), []); self.assertTrue(d["derivation"]["complete"]); self.assertEqual(d["derivation"]["missing_sizes"], [])
        more = next(x for n in d["nodes"] for x in n["deviations"] if x["id"].endswith("flow-more")); self.assertEqual((more["size"], more["assumed"]), ({"relative": 0.2}, SIZES["reason"]))
        self.assertTrue(any("sizes were supplied by the team" in w for w in d["derivation"]["warnings"]))
        ws = hazop.run_study(d, c, solve=lambda cc, pk: {"ran": True, "solved": True, "sim": sim(), "findings": []}); self.assertEqual(ws["summary"]["deviations"], 16)     # the derived spec runs end to end

    def test_a_sizes_table_without_a_reason_is_refused_and_bad_sizes_stay_missing(self):
        g = line_graph()
        for bad in ({"flow": {"MORE": {"relative": 0.2}}}, {"reason": "  ", "flow": {}}): 
            with self.assertRaisesRegex(ValueError, "needs a reason"): N.derive(g, None, "s", bad)
        d = N.derive(g, None, "s", {"reason": "r", "temperature": {"MORE": {"relative": 0.1}}})                      # a relative temperature size is not allowed: left missing
        self.assertIn("f-temperature-more", d["derivation"]["missing_sizes"]); self.assertEqual(len(d["derivation"]["missing_sizes"]), 6)
        d = N.derive(g, None, "s", {"reason": "r", "flow": {"MORE": {"relative": 0.1, "absolute": 5}}}); self.assertIn("f-flow-more", d["derivation"]["missing_sizes"])


class Warnings(unittest.TestCase):
    def test_unreviewed_extraction_is_flagged(self):
        d = N.derive(line_graph(flags=["needs-signoff"]), None, "s")["derivation"]; self.assertTrue(any("unreviewed P&ID extraction: 4 unit(s)" in w for w in d["warnings"])); self.assertTrue(all(x["needs_signoff"] for x in d["units"].values()))
        self.assertFalse(any("unreviewed" in w for w in N.derive(line_graph(), None, "s")["derivation"]["warnings"]))

    def test_reconcile_findings_are_passed_through(self):
        d = N.derive(line_graph(), None, "s", issues=["warn X: isolated unit", "error Y: self-loop"])["derivation"]; self.assertTrue(any("reconcile reports 2 finding(s)" in w and "isolated unit" in w for w in d["warnings"]))

    def test_feed_problems(self):
        g = graph([("U", "heater", [])], [("F", "feed", None, None), ("OUT", "product", "U", None)]); d = N.derive(g, None, "s")
        self.assertEqual(d["nodes"], []); self.assertTrue(any("does not enter any unit" in w for w in d["derivation"]["warnings"]))
        self.assertTrue(any("has no feed stream entering a unit" in w for w in d["derivation"]["warnings"])); self.assertFalse(d["derivation"]["complete"])
        g = graph([("U", "heater", [])], [("G", "feed", "U", "U"), ("OUT", "product", "U", None)]); d = N.derive(g, None, "s")      # a "feed" that has a source unit is reported, and the draft is not complete
        self.assertTrue(any("not a feed" in e for e in d["derivation"]["errors"])); self.assertFalse(d["derivation"]["complete"])

    def test_tag_mismatches_with_the_case(self):
        c = schema.load(os.path.join(CASES, "water-heater-cooler-tutorial.json")); g = N.graph_from_case(c); self.assertEqual(N.match_case(g, c), [])
        g2 = copy.deepcopy(g); g2["units"]["H"]["type"] = "cooler"; g2["units"]["XX"] = {"type": "pump", "flags": []}; del g2["streams"]["COLD"]
        m = " | ".join(N.match_case(g2, c)); self.assertIn("unit H is a cooler in the topology and a heater in the case", m); self.assertIn("unit XX is not in case", m); self.assertIn("feed COLD of the case is not a feed in the topology", m)
        g3 = N.graph_from_case(c); g3["streams"]["HOT"]["role"] = "feed"; self.assertIn("feed HOT is not a feed stream of case", " | ".join(N.match_case(g3, c)))
        self.assertTrue(N.derive(g2, c, "s")["derivation"]["mismatches"]); self.assertFalse(N.derive(g2, c, "s", SIZES)["derivation"]["complete"])

    def test_a_case_unit_missing_from_the_topology_is_a_mismatch(self):
        c = schema.load(os.path.join(CASES, "water-heater-cooler-tutorial.json")); g = N.graph_from_case(c); del g["units"]["H"]
        self.assertTrue(any("unit H of the case is not in the topology" in m for m in N.match_case(g, c)))

    def test_a_feed_with_a_source_unit_alone_makes_the_draft_incomplete(self):
        c = schema.load(os.path.join(CASES, "water-heater-cooler-tutorial.json")); g = N.graph_from_case(c); feed = next(s for s, x in g["streams"].items() if x["role"] == "feed"); g["streams"][feed]["src"] = next(iter(g["units"]))
        d = N.derive(g, c, "s", SIZES); self.assertEqual(d["derivation"]["mismatches"], []); self.assertTrue(d["derivation"]["errors"]); self.assertFalse(d["derivation"]["complete"])

    def test_no_case_means_no_case_in_the_spec(self):
        d = N.derive(line_graph(), None, "s", SIZES); self.assertIsNone(d["case"]); self.assertTrue(d["derivation"]["mismatches"]); self.assertFalse(d["derivation"]["complete"])

    def test_unrunnable_case_is_drafted_with_a_warning(self):
        c = schema.load(os.path.join(CASES, "mch-extractive-distillation-aspen-getting-started.json")); d = N.derive(N.graph_from_case(c), c, "s")
        self.assertTrue(any("cannot be run on the DWSIM backend" in w for w in d["derivation"]["warnings"])); self.assertEqual(len(d["nodes"]), 2)

    def test_limits_are_stated(self):
        self.assertIn("no controller cause is derived", N.derive(line_graph(), None, "s")["derivation"]["limits"])


class Everywhere(unittest.TestCase):
    def test_every_casebook_case_derives_and_validates_once_sized(self):
        for f in sorted(glob.glob(os.path.join(CASES, "*.json"))):
            c = schema.load(f); d = N.derive(N.graph_from_case(c), c, "s", SIZES)
            self.assertEqual(hazop.validate_spec(d, c), [], c["id"]); self.assertEqual(d["derivation"]["mismatches"], [], c["id"]); self.assertGreaterEqual(len(d["nodes"]), 1, c["id"])


class FlowsheetAndTool(unittest.TestCase):
    def fs(self):
        f = Flowsheet("pid", "Peng-Robinson", ["Water"])
        f.units = {"P-101": Unit("P-101", "pump", flags=["needs-signoff"]), "E-101": Unit("E-101", "heater", flags=["needs-signoff"]), "ORPHAN": Unit("ORPHAN", "valve", flags=["needs-signoff"])}
        f.streams = {"1": Stream("1", "feed", None, "P-101"), "2": Stream("2", "intermediate", "P-101", "E-101"), "3": Stream("3", "product", "E-101", None)}; f.relink(); return f

    def test_graph_from_a_flowsheet_and_the_tool_with_a_session(self):
        g = N.graph_from_flowsheet(self.fs()); self.assertEqual(g["streams"]["1"], {"role": "feed", "src": None, "dst": "P-101"})
        with mock.patch.dict(M.SESSIONS, {"pidx": self.fs()}):
            out = tools.t_hazop_nodes({"session": "pidx", "study_id": "from-pid"})
        sp = out["spec"]; self.assertEqual(sp["nodes"][0]["upstream_equipment"], ["heater", "pump"]); self.assertFalse(out["complete"]); w = " | ".join(sp["derivation"]["warnings"])
        self.assertIn("unreviewed P&ID extraction: 3 unit(s)", w); self.assertIn("reconcile reports", w); self.assertIn("isolated unit", w)             # ORPHAN has no streams: reconcile says so
        self.assertEqual(sp["derivation"]["from"], "flowsheet (P&ID extraction or other)")

    def test_the_session_is_not_modified_and_the_tool_writes_nothing(self):
        f = self.fs(); before = json.dumps({k: vars(v) for k, v in f.units.items()}, default=str, sort_keys=True)
        with mock.patch.dict(M.SESSIONS, {"pidx": f}): tools.t_hazop_nodes({"session": "pidx"})
        self.assertEqual(json.dumps({k: vars(v) for k, v in f.units.items()}, default=str, sort_keys=True), before); self.assertIn("ORPHAN", f.units)          # reconcile ran on a copy, no fix applied

    def test_case_tool_and_argument_rules(self):
        self.assertIn("casebook_hazop_nodes", M.TOOLS)
        out = tools.t_hazop_nodes({"case_id": "water-heater-cooler-tutorial", "sizes": SIZES}); self.assertTrue(out["complete"])
        with self.assertRaisesRegex(ValueError, "case_id"): tools.t_hazop_nodes({})
        with self.assertRaises(KeyError): tools.t_hazop_nodes({"session": "nothing-loaded"})
        with self.assertRaisesRegex(ValueError, "needs a reason"): tools.t_hazop_nodes({"case_id": "water-heater-cooler-tutorial", "sizes": {"flow": {}}})


if __name__ == "__main__": unittest.main()
