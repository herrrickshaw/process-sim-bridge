import copy, json, os, tempfile, unittest
from unittest import mock
from hysys_bridge.casebook import hazop, schema, tools, runner, guardrails
from hysys_bridge.tests.test_casebook import FakeTransport, CASE

HX = os.path.join(os.path.dirname(CASE), "water-counter-current-exchanger-tutorial.json")
STUDY = os.path.join(os.path.dirname(CASE), "..", "hazop", "example-water-exchanger-deviations.json")


def jload(p):
    with open(p) as f: return json.load(f)
def jdump(o, p):
    with open(p, "w") as f: json.dump(o, f)
def hx(): return schema.load(HX)
def spec(**kw):
    s = {"id": "t", "case": "water-counter-current-exchanger-tutorial", "packages": ["Steam Tables"],
         "nodes": [{"id": "n1", "stream": "HOT_IN", "deviations": [{"id": "d1", "parameter": "flow", "guide_word": "MORE", "size": {"relative": 0.5}, "assumed": "test size"}]}]}
    s.update(kw); return s
def dev(**kw):
    d = {"id": "d1", "parameter": "flow", "guide_word": "MORE", "size": {"relative": 0.5}, "assumed": "test size"}; d.update(kw); return d
def with_dev(**kw): s = spec(); s["nodes"][0]["deviations"] = [dev(**kw)]; return s


class Validation(unittest.TestCase):
    def problems(self, s): return hazop.validate_spec(s, hx())
    def test_good_spec_and_the_example_study_validate(self):
        self.assertEqual(self.problems(spec()), []); ex = jload(STUDY); self.assertEqual(self.problems(ex), [])

    def test_every_rule_fires(self):
        bad = [("is not a feed stream", lambda s: s["nodes"][0].update(stream="HOT_OUT")),
               ("is not this case", lambda s: s.update(case="other")),
               ("nodes is empty", lambda s: s.update(nodes=[])),
               ("duplicated", lambda s: s["nodes"].append(copy.deepcopy(s["nodes"][0]))),
               ("no deviations", lambda s: s["nodes"][0].update(deviations=[])),
               ("not supported", lambda s: s["nodes"][0]["deviations"][0].update(guide_word="NONE", parameter="temperature")),
               ("not supported", lambda s: s["nodes"][0]["deviations"][0].update(guide_word="AS_WELL_AS")),
               ("needs an anchor or an assumed reason", lambda s: s["nodes"][0]["deviations"][0].pop("assumed")),
               ("size must be", lambda s: s["nodes"][0]["deviations"][0].update(size={"relative": 0.1, "absolute": 5})),
               ("size must be", lambda s: s["nodes"][0]["deviations"][0].update(size={"relative": -0.1})),
               ("size must be", lambda s: s["nodes"][0]["deviations"][0].pop("size")),
               ("relative temperature change is meaningless", lambda s: s["nodes"][0]["deviations"][0].update(parameter="temperature", size={"relative": 0.1})),
               ("removes the quantity", lambda s: s["nodes"][0]["deviations"][0].update(guide_word="LESS", size={"relative": 1.0})),
               ("takes no size", lambda s: s["nodes"][0]["deviations"][0].update(guide_word="NONE", size={"relative": 0.1})),
               ("need a compound", lambda s: s["nodes"][0]["deviations"][0].update(parameter="composition", guide_word="PART_OF", size={"relative": 0.5})),
               ("is not in the case's compounds", lambda s: s["nodes"][0]["deviations"][0].update(parameter="composition", guide_word="PART_OF", compound="Gold", size={"relative": 0.5})),
               ("AS_WELL_AS needs size", lambda s: s["nodes"][0]["deviations"][0].update(parameter="composition", guide_word="AS_WELL_AS", compound="Water", size={"fraction": 1.5})),
               ("safeguards must be a list", lambda s: s["nodes"][0]["deviations"][0].update(safeguards="x")),
               ("id missing, malformed or duplicated", lambda s: s["nodes"][0]["deviations"][0].update(id="Bad Id")),
               ("watch", lambda s: s.update(watch=[{"stream": "NOPE", "property": "T"}])),
               ("packages must be", lambda s: s.update(packages=["Gold EOS"])),
               ("design_limits", lambda s: s.update(design_limits={"streams": {"NOPE": {"T_C": {"max": 1}, "anchor": "x"}}}))]
        for needle, mut in bad:
            s = spec(); mut(s); self.assertTrue(any(needle in x for x in self.problems(s)), needle)

    def test_run_refuses_an_invalid_spec(self):
        s = spec(); s["nodes"][0]["stream"] = "HOT_OUT"
        with self.assertRaisesRegex(ValueError, "not a feed stream"): hazop.run_study(s, hx(), solve=lambda c, p: {})


class Apply(unittest.TestCase):
    def go(self, stream, **kw):
        c, a = hazop.apply_deviation(hx(), stream, dev(**kw)); return next(x for x in c["streams"] if x["id"] == stream), a
    def test_flow(self):
        s, a = self.go("HOT_IN"); self.assertAlmostEqual(s["mass_flow"]["value"], 5400.0); self.assertEqual((a["before"], a["after"]), (3600.0, 5400.0))
        self.assertAlmostEqual(self.go("HOT_IN", guide_word="LESS", size={"relative": 0.25})[0]["mass_flow"]["value"], 2700.0)
        self.assertAlmostEqual(self.go("HOT_IN", size={"absolute": 100})[0]["mass_flow"]["value"], 3700.0)
        s, a = self.go("HOT_IN", guide_word="NONE", size=None); self.assertAlmostEqual(s["mass_flow"]["value"], 3600 * hazop.NONE_FLOW_FRACTION); self.assertIn("zero flow cannot be solved", a["note"])
        with self.assertRaises(ValueError): self.go("HOT_IN", guide_word="LESS", size={"absolute": 4000})

    def test_temperature_and_pressure(self):
        s, _ = self.go("HOT_IN", parameter="temperature", size={"absolute": 15}); self.assertAlmostEqual(s["T"]["value"], 126.85 + 15)
        s, _ = self.go("HOT_IN", parameter="temperature", guide_word="LESS", size={"absolute": 15}); self.assertAlmostEqual(s["T"]["value"], 126.85 - 15)
        s, a = self.go("COLD_IN", parameter="pressure", guide_word="LESS", size={"absolute": 20}); self.assertAlmostEqual(s["P"]["value"], 101.325 - 20); self.assertIn("kPa", a["note"])
        s, _ = self.go("COLD_IN", parameter="pressure", size={"relative": 0.1}); self.assertAlmostEqual(s["P"]["value"], 101.325 * 1.1)
        with self.assertRaises(ValueError): self.go("COLD_IN", parameter="pressure", guide_word="LESS", size={"absolute": 200})
        c = hx(); next(x for x in c["streams"] if x["id"] == "COLD_IN")["P"].update(value=1.0, unit="bar")               # 1 bar stored in bar, size in kPa
        out, _ = hazop.apply_deviation(c, "COLD_IN", dev(parameter="pressure", size={"absolute": 50})); self.assertAlmostEqual(next(x for x in out["streams"] if x["id"] == "COLD_IN")["P"]["value"], 1.5)

    def test_composition(self):
        c = schema.load(CASE); feed = next(x for x in c["streams"] if x["role"] == "feed" and len(x["composition"]["values"]) > 1); comp = sorted(feed["composition"]["values"])[0]
        out, a = hazop.apply_deviation(c, feed["id"], dev(parameter="composition", guide_word="PART_OF", compound=comp, size={"relative": 0.5})); v = next(x for x in out["streams"] if x["id"] == feed["id"])["composition"]["values"]
        self.assertAlmostEqual(sum(v.values()), 1.0, places=9); self.assertAlmostEqual(v[comp], feed["composition"]["values"][comp] * 0.5, places=9); self.assertEqual(schema.validate(out), [])
        out, a = hazop.apply_deviation(c, feed["id"], dev(parameter="composition", guide_word="AS_WELL_AS", compound=comp, size={"fraction": 0.1})); v = next(x for x in out["streams"] if x["id"] == feed["id"])["composition"]["values"]
        self.assertAlmostEqual(sum(v.values()), 1.0, places=9); self.assertAlmostEqual(v[comp], feed["composition"]["values"][comp] * 0.9 + 0.1, places=9)
        with self.assertRaises(ValueError): hazop.apply_deviation(hx(), "HOT_IN", dev(parameter="composition", guide_word="PART_OF", compound="Water", size={"relative": 0.5}))      # a pure stream cannot be renormalised

    def test_the_input_case_is_not_modified(self):
        c = hx(); before = json.dumps(c, sort_keys=True); hazop.apply_deviation(c, "HOT_IN", dev()); self.assertEqual(json.dumps(c, sort_keys=True), before)


def sim(hot_out_T=86.1, cold_T=47.4, mass=3600.0, vf=0.0):
    st = lambda T, P, m, v=0.0: {"T": T, "P": P, "mass": m, "vapor_fraction": v, "mass_fractions": {"Water": 1.0}}
    return {"HOT_IN": st(126.85, 304.0, mass), "COLD_IN": st(26.85, 101.325, 7200.0), "HOT_OUT": st(hot_out_T, 294.0, mass), "COLD_OUT": st(cold_T, 96.3, 7200.0, vf)}


class Run(unittest.TestCase):
    LIM = {"streams": {"HOT_OUT": {"T_C": {"max": 100.0}, "anchor": "test"}}}
    def solver(self, table):
        calls = []
        def f(case, pk):
            calls.append(pk); m = next(s for s in case["streams"] if s["id"] == "HOT_IN")["mass_flow"]["value"]
            return table(m) if callable(table) else table
        f.calls = calls; return f

    def test_new_violation_unchanged_baseline_and_watch(self):
        sp = spec(design_limits=self.LIM, watch=[{"stream": "HOT_OUT", "property": "T"}]); sv = self.solver(lambda m: {"ran": True, "solved": True, "sim": sim(hot_out_T=86.1 if m == 3600 else 110.0), "findings": []})
        ws = hazop.run_study(sp, hx(), solve=sv); r = ws["rows"][0]
        self.assertTrue(r["solved"]); self.assertEqual(r["watch"][0]["baseline"], 86.1); self.assertAlmostEqual(r["watch"][0]["delta"], 23.9)
        v = [c for c in r["consequences"] if c["kind"] == "limit_violation"]; self.assertEqual(len(v), 1); self.assertTrue(v[0]["new"]); self.assertEqual(ws["summary"]["with_new_violation"], 1)
        always = self.solver(lambda m: {"ran": True, "solved": True, "sim": sim(hot_out_T=110.0), "findings": []})            # the baseline already violates: not new
        w2 = hazop.run_study(sp, hx(), solve=always); r2 = w2["rows"][0]; self.assertEqual(r2["consequences"][0]["new"], False); self.assertEqual(w2["summary"]["with_new_violation"], 0)
        self.assertIn("(already in the baseline)", hazop.render_markdown(w2))

    def test_advisory_findings_are_reported_as_advisories(self):
        lim = {"vessels": {"V": {"stream": "HOT_OUT", "design_temperature_C": 140.0, "anchor": "test"}}}                  # design margin rule: advisory when the operating temperature rises
        sv = self.solver(lambda m: {"ran": True, "solved": True, "sim": sim(hot_out_T=86.1 if m == 3600 else 120.0), "findings": []})
        r = hazop.run_study(spec(design_limits=lim), hx(), solve=sv)["rows"][0]; kinds = [(c["kind"], c["rule"], c["new"]) for c in r["consequences"]]
        self.assertIn(("advisory", "forum-vessel-design-temperature-margin", True), kinds)
        r0 = hazop.run_study(spec(design_limits=lim), hx(), solve=self.solver({"ran": True, "solved": True, "sim": sim(hot_out_T=86.1), "findings": []}))["rows"][0]
        self.assertFalse([c for c in r0["consequences"] if c["kind"] == "advisory" and c["new"]])                         # at the baseline margin (53.9 C) the rule passes

    def test_solver_warnings_are_listed_as_findings(self):
        sv = self.solver(lambda m: {"ran": True, "solved": True, "sim": sim(), "findings": [] if m == 3600 else [{"code": "HX_TEMPERATURE_CROSS", "severity": "warning", "object": "X", "simulator_fix": "check the T-Q diagram"}]})
        r = hazop.run_study(spec(), hx(), solve=sv)["rows"][0]; f = [c for c in r["consequences"] if c["kind"] == "solver_finding"]
        self.assertEqual((f[0]["rule"], f[0]["object"]), ("HX_TEMPERATURE_CROSS", "X")); self.assertIn("check the T-Q diagram", f[0]["text"])

    def test_no_solution_reverse_and_none_are_distinct_outcomes(self):
        s = spec(design_limits=self.LIM); s["nodes"][0]["deviations"] = [dev(id="fails", guide_word="NONE", size=None), dev(id="rev", guide_word="REVERSE", size=None)]
        sv = self.solver(lambda m: {"ran": True, "solved": True, "sim": sim(), "findings": []} if m == 3600 else {"ran": True, "solved": False, "why": {"errors": ["X: failed to calculate NTU"]}, "findings": [{"code": "NOT_CONVERGED"}]})
        ws = hazop.run_study(s, hx(), solve=sv); a, b = ws["rows"]
        self.assertFalse(a["solved"]); self.assertEqual(a["consequences"][0]["kind"], "no_solution"); self.assertIn("failed to calculate NTU", a["consequences"][0]["text"]); self.assertIn("NOT_CONVERGED", a["consequences"][0]["text"])
        self.assertIs(b["evaluable"], False); self.assertEqual(b["consequences"][0]["kind"], "not_evaluable"); self.assertEqual((ws["summary"]["no_solution"], ws["summary"]["not_evaluable"]), (1, 1))
        self.assertEqual(len(sv.calls), 2)                                                                                      # baseline plus the one evaluable deviation: REVERSE never solves

    def test_baseline_failure_is_an_error_and_no_limits_is_a_warning(self):
        with self.assertRaisesRegex(RuntimeError, "does not solve"): hazop.run_study(spec(), hx(), solve=lambda c, p: {"ran": True, "solved": False, "why": "x"})
        ws = hazop.run_study(spec(), hx(), solve=lambda c, p: {"ran": True, "solved": True, "sim": sim(), "findings": []}); self.assertTrue(any("no safe limits" in w for w in ws["warnings"]))
        self.assertEqual(hazop.run_study(spec(design_limits=self.LIM), hx(), solve=lambda c, p: {"ran": True, "solved": True, "sim": sim(), "findings": []})["warnings"], [])

    def test_every_package_runs_and_gaps_are_listed(self):
        sv = self.solver({"ran": True, "solved": True, "sim": sim(), "findings": []}); two = spec(packages=["Steam Tables", "Peng-Robinson"])
        ws = hazop.run_study(two, hx(), solve=sv); self.assertEqual([r["package"] for r in ws["rows"]], ["Steam Tables", "Peng-Robinson"]); self.assertEqual(sv.calls, ["Steam Tables", "Steam Tables", "Peng-Robinson", "Peng-Robinson"])
        self.assertEqual(ws["gaps"][0]["parameters_without_a_deviation"], ["composition", "pressure", "temperature"])

    def test_causes_and_safeguards_are_carried_and_nothing_is_ranked(self):
        s = spec(); s["nodes"][0]["deviations"][0].update(cause="valve fails open", safeguards=["PSV-1"])
        ws = hazop.run_study(s, hx(), solve=lambda c, p: {"ran": True, "solved": True, "sim": sim(), "findings": []}); r = ws["rows"][0]
        self.assertEqual((r["cause"], r["safeguards"]), ("valve fails open", ["PSV-1"])); self.assertFalse({"severity", "likelihood", "risk", "recommendation"} & set(r)); self.assertIn("no severity", ws["note"])
        ws["about"] = "SYNTHETIC demo"; self.assertIn("**About this study:** SYNTHETIC demo", hazop.render_markdown(ws)); ws["about"] = None
        md = hazop.render_markdown(ws); self.assertNotIn("About this study", md); self.assertIn("valve fails open", md); self.assertIn("PSV-1", md); self.assertIn("Steady-state simulation only", md)

    def test_end_to_end_with_the_fake_server(self):
        c = schema.load(CASE); feed = next(x for x in c["streams"] if x["role"] == "feed")
        sp = {"id": "fake-run", "case": c["id"], "packages": [c["basis"]["package_in_paper"]], "watch": [{"stream": feed["id"], "property": "mass"}],
              "nodes": [{"id": "n", "stream": feed["id"], "deviations": [dev(id="more", size={"relative": 0.2})]}]}
        ws = hazop.run_study(sp, c, transport_factory=FakeTransport); w = ws["rows"][0]["watch"][0]
        self.assertAlmostEqual(w["deviated"] / w["baseline"], 1.2, places=3); self.assertAlmostEqual(ws["rows"][0]["applied"]["after"], feed["mass_flow"]["value"] * 1.2)


class Tool(unittest.TestCase):
    def test_tool_runs_a_study_from_the_operator_directory_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            c = schema.load(CASE); feed = next(x for x in c["streams"] if x["role"] == "feed")
            jdump(c, os.path.join(d, c["id"] + ".json"))
            jdump({"id": "s1", "case": c["id"], "nodes": [{"id": "n", "stream": feed["id"], "deviations": [dev(id="more")]}]}, os.path.join(d, "s1.json"))
            with mock.patch.dict(os.environ, {"CASEBOOK_DIR": d, "HAZOP_DIR": d}), mock.patch.object(runner, "default_transport", FakeTransport):
                before = sorted(os.listdir(d)); out = tools.t_hazop({"spec_id": "s1", "live": True}); self.assertEqual(sorted(os.listdir(d)), before)
            self.assertTrue(out["ran"]); self.assertIn("HAZOP deviation worksheet", out["markdown"]); self.assertIn("casebook_hazop", tools.TOOLS)
            with mock.patch.dict(os.environ, {"CASEBOOK_DIR": d, "HAZOP_DIR": d}):
                jdump({"id": "s2", "case": c["id"], "nodes": [{"id": "n", "stream": "NOPE", "deviations": [dev()]}]}, os.path.join(d, "s2.json"))
                r = tools.t_hazop({"spec_id": "s2"}); self.assertFalse(r["ran"]); self.assertTrue(r["problems"])
                with self.assertRaises(ValueError): tools.t_hazop({"spec_id": "../x"})
                with self.assertRaises(KeyError): tools.t_hazop({"spec_id": "nope"})

    def test_example_study_is_labelled_synthetic(self):
        ex = jload(STUDY); self.assertTrue(ex["example"]); self.assertIn("SYNTHETIC", ex["about"])
        for s in ex["design_limits"]["streams"].values(): self.assertIn("SYNTHETIC", s["anchor"])


if __name__ == "__main__": unittest.main()
