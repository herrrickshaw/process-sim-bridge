import copy, json, os, shutil, tempfile, unittest
from unittest import mock
from hysys_bridge import mcp_server as M
from hysys_bridge.casebook import schema, runner, ledger, diagnose
from hysys_bridge.dwsim.fake import FakeDwsim

CASE = os.path.join(os.path.dirname(__file__), "..", "..", "studies", "cases", "cumene-alkylator-feed-heater.json")
MIXER = os.path.join(os.path.dirname(__file__), "..", "..", "studies", "cases", "water-mixer-tutorial.json")
FLASH = os.path.join(os.path.dirname(__file__), "..", "..", "studies", "cases", "water-ethanol-flash-drum-tutorial.json")
HEATCOOL = os.path.join(os.path.dirname(__file__), "..", "..", "studies", "cases", "water-heater-cooler-tutorial.json")
CONDENSER = os.path.join(os.path.dirname(__file__), "..", "..", "studies", "cases", "steam-condenser-cooler-independent.json")
LOOP = os.path.join(os.path.dirname(__file__), "..", "..", "studies", "cases", "water-recycle-loop-tutorial.json")


def call(tool, **args):
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})["result"]
    t = r["content"][0]["text"]; return r["isError"], (t if r["isError"] else json.loads(t))


class EnthalpyFake(FakeDwsim):
    """FakeDwsim with an invented but deterministic enthalpy h = 1*T kJ/kg, so duty = (Tout - Tin) * mass: plumbing test only."""
    def call(self, tool, args):
        r = super().call(tool, args)
        if tool == "dwsim_stream_get_results":
            kg_s = r["mass_flow_kg_s"] or self.objects["TO_HEATER"]["mass_flow_kg_s"]; r["mass_flow_kg_s"] = kg_s
            r["phases"] = [{"name": "Mixture", "enthalpy_kJ_kg": 1.0 * (r["temperature_K"] - 273.15), "compounds": {}}, {"name": "Vapor", "fraction": 0.0}]
        return r


class FakeTransport:
    def __init__(self): self.fake = EnthalpyFake()
    def call(self, tool, args): return self.fake.call(tool, args)
    def close(self): pass


def case(): return schema.load(CASE)


class Schema(unittest.TestCase):
    def test_the_real_case_is_valid_and_buildable(self):
        c = case(); self.assertEqual(schema.validate(c), []); self.assertTrue(schema.capability(c)["buildable"])

    def planted(self, mutate, needle, n=1):
        c = case(); mutate(c); probs = schema.validate(c)
        self.assertTrue(any(needle in x for x in probs), (needle, probs))
        self.assertEqual(len(probs), n, probs)                       # the fault is reported once, not once per scenario, and nothing else breaks

    def test_each_planted_fault_is_caught(self):
        feed = lambda c: c["streams"][0]
        self.planted(lambda c: feed(c)["T"].pop("anchor"), "anchor")
        self.planted(lambda c: feed(c)["P"].pop("basis"), "P.basis")
        self.planted(lambda c: feed(c)["composition"]["values"].update(Benzene=0.5), "sums to")
        self.planted(lambda c: feed(c)["composition"].pop("check"), "reconstructed")
        self.planted(lambda c: feed(c)["composition"]["values"].update(Xenon=0.0), "not in basis.compounds", n=2)             # also lacks a provenance entry
        self.planted(lambda c: c.update(status="verified"), "review.human")
        self.planted(lambda c: c["reported"][0].update(target="NOPE"), "target")
        self.planted(lambda c: c["reported"].clear(), "reported is empty")
        self.planted(lambda c: c["source"].pop("licence"), "source.licence")
        self.planted(lambda c: c["basis"].pop("molar_mass_g_mol"), "molar_mass_g_mol")
        self.planted(lambda c: c["scenarios"][0].pop("why"), "why")
        self.planted(lambda c: c["scenarios"][0]["overrides"][0].update(path=["composition", "nope"]), "override path")
        self.planted(lambda c: c["scenarios"][0]["overrides"][0].update(set={"Propylene": 0.5, "Benzene": 0.2}), "sums to")
        self.planted(lambda c: c["tolerance"].update(pass_rel=0), "pass_rel")
        self.planted(lambda c: c.update(reproduce={"expected": {"Bogus": 1}, "rel_tol": 0.1, "source": "x"}), "reproduce")

    def test_structural_faults(self):
        feed = lambda c: c["streams"][0]
        self.planted(lambda c: c.pop("units"), "missing 'units'")
        self.planted(lambda c: c["source"].pop("url"), "doi or a url")
        self.planted(lambda c: c["source"].update(read="skimmed"), "source.read")
        self.planted(lambda c: c["basis"].update(packages=[]), "basis.packages", n=2)                                   # also breaks the reproduce check
        self.planted(lambda c: c.update(status="finished"), "status must be")
        self.planted(lambda c: c.pop("review"), "review.method")
        self.planted(lambda c: c["units"][0].update(type="teleporter"), "unknown")
        self.planted(lambda c: c["units"].append(dict(c["units"][0])), "duplicated")
        self.planted(lambda c: c["streams"].append(dict(c["streams"][1])), "duplicated")
        self.planted(lambda c: c["streams"][1].update(role="heap"), "role must be")
        self.planted(lambda c: feed(c).update(src="HE100"), "a feed has no src")
        self.planted(lambda c: c["streams"][1].update(dst="HE100"), "a product has no dst")
        self.planted(lambda c: c["streams"][1].update(src="HE999"), "is not a unit")
        self.planted(lambda c: feed(c)["T"].update(value="hot"), "numeric value")
        self.planted(lambda c: feed(c)["T"].update(unit="F"), "unit 'F'")
        self.planted(lambda c: feed(c)["composition"]["provenance"].update(Benzene="guessed"), "must be reported, assumed or reconstructed")
        self.planted(lambda c: feed(c)["composition"]["provenance"].pop("Benzene"), "must cover every compound")
        self.planted(lambda c: c["reported"].append(dict(c["reported"][0])), "duplicated")
        self.planted(lambda c: c["reported"][0].update(kind="duty"), "kind must be")
        self.planted(lambda c: c["reported"].append({**c["reported"][0], "name": "t_out", "kind": "stream_T_C", "unit": "C", "target": "HE100"}), "must be a stream id")
        self.planted(lambda c: c["scenarios"].append(dict(c["scenarios"][0])), "id missing, duplicated or 'base'", n=1)
        self.planted(lambda c: c["scenarios"][0].update(id="base"), "id missing, duplicated or 'base'")
        self.planted(lambda c: c["scenarios"][0].update(overrides=[]), "overrides is empty")

    def test_flowsheet_conversion(self):
        fs = schema.to_flowsheet(case(), "SRK")
        self.assertAlmostEqual(fs.streams["TO_HEATER"].P_kPa, (34.38675 + 1.01325) * 100)                 # gauge -> absolute
        self.assertAlmostEqual(sum(fs.streams["TO_HEATER"].composition.values()), 1.0)                      # mass fractions sum to 1
        self.assertAlmostEqual(fs.streams["TO_HEATER"].composition["Propylene"], 0.00574 * 42.081 / (0.00574 * 42.081 + 0.99426 * 78.114), places=9)
        self.assertEqual(fs.units["HE100"].inlets, ["TO_HEATER"]); self.assertEqual(fs.units["HE100"].outlets, ["TO_ALKYLATOR"])

    def test_scenarios_change_only_what_they_say(self):
        c = case(); s = schema.apply_scenario(c, "mass-from-mole-flow")
        self.assertNotEqual(s["streams"][0]["mass_flow"]["value"], c["streams"][0]["mass_flow"]["value"]); self.assertEqual(s["streams"][0]["T"], c["streams"][0]["T"])
        self.assertAlmostEqual(s["streams"][0]["mass_flow"]["value"] / c["streams"][0]["mass_flow"]["value"] - 1, 0.0040, delta=0.0005)    # the documented 0.4%
        self.assertEqual(schema.apply_scenario(c, "base"), c); self.assertIsNot(schema.apply_scenario(c, "base"), c)
        with self.assertRaises(KeyError): schema.apply_scenario(c, "nope")

    def test_capability_blocks_unverified_units(self):
        c = case(); c["units"][0]["type"] = "column"; self.assertEqual(schema.capability(c), {"buildable": False, "unverified_unit_types": ["column"]})
        self.assertFalse(runner.run_case(c, FakeTransport)["ran"])


class Runner(unittest.TestCase):
    def test_runs_every_scenario_and_package_and_compares(self):
        c = case(); run = runner.run_case(c, FakeTransport)
        self.assertEqual(len(run["results"]), 9); self.assertTrue(all(o["solved"] for o in run["results"]))
        v = run["results"][0]["values"]["heater_duty"]; want = (170.0 - 72.429121) * 1071616.0                 # fake enthalpy: 1 kJ/kg/K
        self.assertAlmostEqual(v["simulated"], want, delta=1e-6 * want); self.assertAlmostEqual(v["rel_err"], want / 210583600.9 - 1)
        self.assertFalse(v["within_tol"]); self.assertFalse(run["all_within_tol"])                             # 1 kJ/kg/K is about half of the real duty: the comparison must say so

    def test_compare_edges(self):
        self.assertTrue(runner.compare(100.0, 104.9, 0.05)["within_tol"]); self.assertFalse(runner.compare(100.0, 105.1, 0.05)["within_tol"])
        self.assertIsNone(runner.compare(0.0, 1.0, 0.05)["rel_err"]); self.assertFalse(runner.compare(0.0, 1.0, 0.05)["within_tol"])

    def test_reproduce_counts_matches(self):
        c = case(); run = runner.run_case(c, FakeTransport, scenarios=["base"])
        self.assertEqual(runner.reproduce(c, run), {"matched": 0, "of": 3, "solved": 3, "total": 3})            # fake numbers do not match the recorded hand run
        sim = run["results"][0]["values"]["heater_duty"]["simulated"]
        c2 = copy.deepcopy(c); c2["reproduce"]["expected"] = {"NRTL": sim, "Peng-Robinson": sim, "SRK": sim}
        self.assertEqual(runner.reproduce(c2, run)["matched"], 3)

    def test_reproduce_uses_the_tolerance(self):
        c = case(); run = runner.run_case(c, FakeTransport, scenarios=["base"]); sim = run["results"][0]["values"]["heater_duty"]["simulated"]
        c["reproduce"]["rel_tol"] = 0.01
        c["reproduce"]["expected"] = {"NRTL": sim * 1.005, "Peng-Robinson": sim * 1.02, "SRK": sim * 0.995}
        self.assertEqual(runner.reproduce(c, run)["matched"], 2)                                                  # within 1%: NRTL and SRK; 2% off: not Peng-Robinson

    def test_package_spread_is_per_scenario(self):
        slope = {"NRTL": 1.0, "Peng-Robinson (PR)": 1.1, "Soave-Redlich-Kwong (SRK)": 1.05}          # the fake records the server's full package names
        class PkgFake(EnthalpyFake):
            def call(self, tool, args):
                r = FakeDwsim.call(self, tool, args)
                if tool == "dwsim_stream_get_results":
                    kg_s = r["mass_flow_kg_s"] or self.objects["TO_HEATER"]["mass_flow_kg_s"]; r["mass_flow_kg_s"] = kg_s
                    r["phases"] = [{"name": "Mixture", "enthalpy_kJ_kg": slope[self.package] * (r["temperature_K"] - 273.15), "compounds": {}}, {"name": "Vapor", "fraction": 0.0}]
                return r
        class T(FakeTransport):
            def __init__(self): self.fake = PkgFake()
        c = case(); run = runner.run_case(c, T); dT = 170.0 - 72.429121
        want = lambda m: 0.1 * dT * m / 210583600.9                                                                # (1.1 - 1.0) * dT * mass / reported
        sp = run["package_spread_rel"]; m_mole = c["scenarios"][1]["overrides"][0]["set"]["value"]
        self.assertAlmostEqual(sp["base"]["heater_duty"], want(1071616.0), places=9)
        self.assertAlmostEqual(sp["mass-from-mole-flow"]["heater_duty"], want(m_mole), places=9)                  # pooled across scenarios it would be larger

    def test_unknown_package_or_scenario_refused(self):
        with self.assertRaises(ValueError): runner.run_case(case(), FakeTransport, packages=["Bogus"])
        with self.assertRaises(ValueError): runner.run_case(case(), FakeTransport, scenarios=["Bogus"])

    def test_no_dwsim_command_is_a_clear_error(self):
        with mock.patch.dict(os.environ): 
            os.environ.pop("DWSIM_MCP_CMD", None)
            with self.assertRaises(RuntimeError) as e: runner.default_transport()
        self.assertIn("DWSIM_MCP_CMD", str(e.exception))


BLOCKER = {"code": "STREAM_DANGLING", "severity": "blocker", "object": "X", "message": "m", "fix": "Connect it."}
WARNING = {"code": "UNIT_HAD_NO_EFFECT", "severity": "warning", "object": "HE100", "message": "m", "fix": "Check the mode."}


def transport_with(check=None, solve=None):
    """EnthalpyFake whose check and solve answers carry the given findings (the real server returned ok=true on a solve with a blocker finding)."""
    class F(EnthalpyFake):
        def call(self, tool, args):
            r = super().call(tool, args)
            if tool == "dwsim_flowsheet_check" and check is not None: r = {**r, "findings": check, "blockers": sum(f["severity"] == "blocker" for f in check)}
            if tool == "dwsim_solve_run" and solve is not None: r = {**r, "findings": solve}
            return r
    class T(FakeTransport):
        def __init__(self): self.fake = F()
    return T


class Findings(unittest.TestCase):
    def run1(self, T):
        return runner.run_case(case(), T, packages=["SRK"], scenarios=["base"])["results"][0]

    def test_check_blocker_stops_the_solve_and_names_the_next_step(self):
        o = self.run1(transport_with(check=[BLOCKER]))
        self.assertFalse(o["solved"]); self.assertEqual(o["why"]["blocked"], "flowsheet check reports blockers")
        self.assertEqual(o["findings"][0]["category"], "case_error"); self.assertIn("Never change a published number", o["next_step"])

    def test_ok_true_with_a_blocker_finding_is_not_solved(self):
        o = self.run1(transport_with(solve=[BLOCKER]))
        self.assertFalse(o["solved"]); self.assertEqual(o["why"]["blocked"], "solve reported blocker findings"); self.assertTrue(o["why"]["findings"])

    def test_warnings_are_kept_on_a_solved_run_and_reach_the_ledger(self):
        run = runner.run_case(case(), transport_with(solve=[WARNING]), packages=["SRK"], scenarios=["base"]); o = run["results"][0]
        self.assertTrue(o["solved"]); self.assertEqual([f["category"] for f in o["findings"]], ["backend_mapping"])
        self.assertEqual(runner.ledger_rows(run)[0]["findings"], ["UNIT_HAD_NO_EFFECT:warning:HE100"])

    def test_clean_run_has_no_findings(self):
        self.assertEqual(self.run1(FakeTransport)["findings"], [])


class Diagnose(unittest.TestCase):
    def test_every_code_is_classified_once(self):
        allc = [c for _, codes in (diagnose.CASE_ERROR, diagnose.BACKEND, diagnose.PLAUSIBILITY, diagnose.CONVERGENCE) for c in codes]
        self.assertEqual(len(allc), len(set(allc)))
        self.assertEqual(diagnose.CATEGORY["FEED_NO_FLOW"][0], "case_error"); self.assertEqual(diagnose.CATEGORY["EFFICIENCY_OUT_OF_RANGE"][0], "backend_mapping")
        self.assertEqual(diagnose.CATEGORY["HX_TEMPERATURE_CROSS"][0], "plausibility"); self.assertEqual(diagnose.CATEGORY["RECYCLE_NO_ESTIMATE"][0], "convergence")

    def test_unknown_code_is_flagged_not_guessed(self):
        c = diagnose.classify([{"code": "NEW_CODE_2027", "severity": "warning", "object": "A"}])[0]
        self.assertEqual(c["category"], "unclassified"); self.assertIn("add it to this table", c["loop_action"])

    def test_next_step_prefers_blockers_then_what_we_can_fix(self):
        mk = lambda code, sev: {"code": code, "severity": sev, "object": "o"}
        cl = diagnose.classify([mk("HEATER_COOLED", "warning"), mk("UNIT_HAD_NO_EFFECT", "warning"), mk("SPEC_MISSING", "warning")])
        self.assertEqual(diagnose.next_step(cl), diagnose.CASE_ERROR[0])                                              # case error beats backend mapping beats plausibility
        cl = diagnose.classify([mk("SPEC_MISSING", "warning"), mk("RECYCLE_NO_ESTIMATE", "blocker")])
        self.assertEqual(diagnose.next_step(cl), diagnose.CONVERGENCE[0])                                                      # a blocker beats a warning
        self.assertIsNone(diagnose.next_step([]))


class LoopFake(FakeDwsim):
    """Stand-in that solves the tutorial loop in closed form from the split ratio the backend sent (SR1): fresh 1 kg/s, mixed = fresh / r, recycle = mixed * (1 - r).
    If the ratio never arrives it answers with 0.5, so a backend that drops the parameter fails the non-base scenarios."""
    honour = True
    def call(self, tool, args):
        r = super().call(tool, args)
        if tool == "dwsim_stream_get_results":
            ratio = self.params.get("SP", {}).get("SR1", 0.5) if self.honour else 0.5; k = {"FRESH": 1.0, "PRODUCT": 1.0, "MIXED": 1 / ratio, "HEATED": 1 / ratio, "RECYCLE": (1 - ratio) / ratio, "RETURN": (1 - ratio) / ratio}[args["name"]]
            r = {**r, "mass_flow_kg_s": k, "phases": []}
        return r


class LoopTransport(FakeTransport):
    def __init__(self): self.fake = LoopFake()


class Recycle(unittest.TestCase):
    def loop(self): return schema.load(LOOP)

    def test_case_is_valid_and_computed_streams_need_no_t_and_p(self):
        c = self.loop(); self.assertEqual(schema.validate(c), []); self.assertTrue(schema.capability(c)["buildable"])
        fs = schema.to_flowsheet(c, "Steam Tables")
        self.assertIsNone(fs.streams["MIXED"].T_C); self.assertIsNone(fs.streams["MIXED"].P_kPa)
        self.assertAlmostEqual(fs.streams["HEATED"].T_C, 76.85); self.assertAlmostEqual(fs.streams["HEATED"].P_kPa, 101.325)       # heater outlet carries the spec
        self.assertEqual(fs.units["SP"].params, {"split_ratio": 0.7}); self.assertEqual(fs.units["RC"].inlets, ["RECYCLE"]); self.assertEqual(fs.units["RC"].outlets, ["RETURN"])
        self.assertEqual(sorted(fs.units["MIX"].inlets), ["FRESH", "RETURN"])

    def test_the_analytic_values_are_consistent(self):
        c = self.loop(); r = {x["name"]: x["value"] for x in c["reported"]}
        self.assertAlmostEqual(r["mixed_flow"], r["product_flow"] / 0.7, places=3); self.assertAlmostEqual(r["recycle_flow"], r["mixed_flow"] * 0.3, places=3)
        for sc in c["scenarios"]:                                                                                  # each scenario's expectation follows its own ratio
            q = {x["name"]: x["value"] for x in schema.apply_scenario(c, sc["id"])["reported"]}; ratio = schema.apply_scenario(c, sc["id"])["units"][2]["params"]["split_ratio"]
            self.assertAlmostEqual(q["mixed_flow"], 3600.0 / ratio, places=3); self.assertAlmostEqual(q["recycle_flow"], q["mixed_flow"] * (1 - ratio), places=3)

    def planted(self, mutate, needle):
        c = self.loop(); mutate(c); probs = schema.validate(c); self.assertTrue(any(needle in x for x in probs), (needle, probs))

    def test_planted_faults(self):
        self.planted(lambda c: c["units"][0].update(params={"split_ratio": 0.5}), "split_ratio")                 # on a mixer
        self.planted(lambda c: c["units"][2]["params"].update(split_ratio=1.5), "split_ratio")
        self.planted(lambda c: c["scenarios"][0]["overrides"][1].update(reported="nope"), "override path")
        self.planted(lambda c: c["streams"][2].pop("T"), "streams[HEATED].T")                                      # heater outlet needs T and P

    def test_backend_sends_the_split_ratio_and_adds_a_recycle(self):
        t = LoopTransport(); run = runner.run_case(self.loop(), lambda: t, packages=["Steam Tables"], scenarios=["base"])
        sets = [(a["name"], a["properties"]) for tool, a in t.fake.calls if tool == "dwsim_unitop_set"]
        self.assertIn(("SP", {"OperationMode": "SplitRatios", "SR1": 0.7}), sets)
        self.assertEqual([a["type"] for tool, a in t.fake.calls if tool == "dwsim_unitop_add"], ["Mixer", "Heater", "Splitter", "Recycle"])
        self.assertTrue(run["results"][0]["solved"])

    def test_every_scenario_matches_the_closed_form(self):
        run = runner.run_case(self.loop(), LoopTransport); self.assertEqual(len(run["results"]), 8)
        self.assertTrue(run["all_within_tol"], [(o["scenario"], {k: v["rel_err"] for k, v in o["values"].items()}) for o in run["results"]])

    def test_a_backend_that_drops_the_ratio_is_caught(self):
        class Deaf(LoopTransport):
            def __init__(self): self.fake = LoopFake(); self.fake.honour = False
        run = runner.run_case(self.loop(), Deaf, packages=["Steam Tables"])
        within = {o["scenario"]: all(v["within_tol"] for v in o["values"].values()) for o in run["results"]}
        self.assertFalse(within["base"]); self.assertTrue(within["split-0.5"])                                    # only the scenario that happens to equal the default passes
        self.assertFalse(run["all_within_tol"])


class FlashFake(FakeDwsim):
    """Water/ethanol flash drum in closed form from the heater outlet temperature: vapour (mole) fraction 0 up to 350 K, 0.55 at 360 K, 1 from 370 K, with 0.64 of the mass in the vapour; vapour carries 0.66
    ethanol, liquid 0.22 (the tutorial's rounded values). The separator's first outlet port gets the vapour, the second the liquid, like the real Vessel."""
    swap = False
    def call(self, tool, args):
        r = super().call(tool, args)
        if tool == "dwsim_stream_get_results":
            t = self.params.get("H", {}).get("OutletTemperature", 360.0); vf = 0.0 if t <= 350 else 1.0 if t >= 370 else 0.55; mshare = 0.0 if t <= 350 else 1.0 if t >= 370 else 0.64; n = args["name"]
            port = {"V": None}; sep = self.ports.get("SEP", {})
            idx = sep.get(n, ("", None))[1] if sep.get(n, ("",))[0] == "product_stream" else None
            if idx is not None and self.swap: idx = 1 - idx
            mass, x_et = {"FEED": (1.0, 0.5), "TWO_PHASE": (1.0, 0.5)}.get(n, (None, None))
            if idx == 0: mass, x_et = mshare, 0.66 if vf else 0.5
            if idx == 1: mass, x_et = 1 - mshare, 0.22 if vf < 1 else 0.5
            r = {**r, "mass_flow_kg_s": mass, "phases": [{"name": "Mixture", "enthalpy_kJ_kg": 0.0, "compounds": {"Water": {"mass_fraction": 1 - x_et}, "Ethanol": {"mass_fraction": x_et}}}, {"name": "Vapor", "fraction": vf if n in ("TWO_PHASE",) else (1.0 if idx == 0 else 0.0)}]}
        return r


class FlashTransport(FakeTransport):
    swap = False
    def __init__(self): self.fake = FlashFake(); self.fake.swap = self.swap


class SwappedFlash(FlashTransport):
    swap = True


class RangesAndFlash(unittest.TestCase):
    def flash(self): return schema.load(FLASH)

    def test_cases_are_valid(self):
        for f in (MIXER, FLASH): self.assertEqual(schema.validate(schema.load(f)), [], f)

    def planted(self, mutate, needle, base=None):
        c = (base or self.flash)(); mutate(c); probs = schema.validate(c); self.assertTrue(any(needle in x for x in probs), (needle, probs))

    def test_range_and_new_kind_faults(self):
        self.planted(lambda c: c["reported"][0].update(range=[0.8, 0.4]), "range must be")
        self.planted(lambda c: c["reported"][0].update(range=[0.4]), "range must be")
        self.planted(lambda c: c["reported"][0].update(unit="kg/h"), "unit")
        self.planted(lambda c: c["reported"][0].pop("anchor"), "anchor")
        self.planted(lambda c: c["reported"][5].update(targets=["VAPOR", "NOPE"]), "targets must be")
        self.planted(lambda c: c["reported"][3].update(compound="Xenon"), "compound must be")
        self.planted(lambda c: c["reported"][6].update(pass_rel=2), "pass_rel")
        self.planted(lambda c: c["scenarios"][0].update(drop_reported="vapor_mass_flow"), "drop_reported")
        self.planted(lambda c: c["streams"].reverse(), "'vapor' then 'liquid'")                                      # file order decides the Vessel's ports
        self.planted(lambda c: c["streams"][2].update(phase="liquid"), "'vapor' then 'liquid'")

    def test_compare_item(self):
        r = {"range": [0.4, 0.8]}; self.assertTrue(runner.compare_item(r, 0.4, 0.05)["within_tol"]); self.assertTrue(runner.compare_item(r, 0.8, 0.05)["within_tol"])
        self.assertFalse(runner.compare_item(r, 0.801, 0.05)["within_tol"]); self.assertFalse(runner.compare_item(r, 0.399, 0.05)["within_tol"])
        self.assertIsNone(runner.compare_item(r, 0.5, 0.05)["rel_err"])
        p = {"value": 100.0, "pass_rel": 0.01}; self.assertTrue(runner.compare_item(p, 100.9, 0.5)["within_tol"]); self.assertFalse(runner.compare_item(p, 101.1, 0.5)["within_tol"])   # own tolerance beats the default
        self.assertTrue(runner.compare_item({"value": 100.0}, 104.0, 0.05)["within_tol"])                                                                                       # default applies

    def test_drop_reported_removes_only_what_it_names(self):
        c = self.flash(); sc = schema.apply_scenario(c, "below-bubble-point"); names = {r["name"] for r in sc["reported"]}; base = {r["name"] for r in c["reported"]}
        self.assertEqual(base - names, {"vapor_ethanol_fraction_enriched", "liquid_ethanol_fraction_depleted", "vapor_mass_flow_approx", "liquid_mass_flow_approx", "vapor_ethanol_fraction_approx", "liquid_ethanol_fraction_approx"})
        self.assertEqual(sc["scenarios"], []); self.assertEqual(schema.validate(sc), [])                              # an applied scenario is a plain case
        self.assertEqual(next(r for r in sc["reported"] if r["name"] == "two_phase_vapor_fraction")["range"], [0.0, 0.001])

    def test_flash_runs_every_scenario_and_passes_the_paper_package(self):
        run = runner.run_case(self.flash(), FlashTransport, packages=["NRTL"])
        self.assertEqual(len(run["results"]), 3); self.assertTrue(run["all_within_tol"], [(o["scenario"], {k: v for k, v in o["values"].items() if not v["within_tol"]}) for o in run["results"]])
        self.assertTrue(run["paper_package_within_tol"])

    def test_swapped_separator_ports_are_caught(self):
        run = runner.run_case(self.flash(), SwappedFlash, packages=["NRTL"]); self.assertFalse(run["all_within_tol"])
        bad = {k for o in run["results"] if o["scenario"] == "base" for k, v in o["values"].items() if not v["within_tol"]}
        self.assertIn("vapor_mass_flow_approx", bad); self.assertIn("vapor_ethanol_fraction_enriched", bad)

    def test_paper_package_is_reported_separately(self):
        class Biased(FlashTransport):                                                                               # every package other than NRTL gets a wrong answer
            def __init__(self):
                super().__init__(); f = self.fake; orig = f.call
                def call(tool, args):
                    r = orig(tool, args)
                    if tool == "dwsim_stream_get_results" and f.package != "NRTL" and args["name"] == "VAPOR": r = {**r, "mass_flow_kg_s": r["mass_flow_kg_s"] * 1.3}
                    return r
                f.call = call
        run = runner.run_case(self.flash(), Biased, scenarios=["base"])
        self.assertTrue(run["paper_package_within_tol"]); self.assertFalse(run["all_within_tol"])

    def test_mixer_case_values_and_a_wrong_temperature_is_caught(self):
        m = schema.load(MIXER); r = {x["name"]: x for x in m["reported"]}
        self.assertEqual(r["outlet_mass"]["value"], 540000.0); self.assertAlmostEqual(r["outlet_T"]["value"], 316.0141 - 273.15, places=4)
        s = {x["name"]: x["value"] for x in schema.apply_scenario(m, "equal-flows")["reported"] if "value" in x}; self.assertEqual(s["outlet_mass"], 720000.0)
        for sid in ("flows-swapped", "equal-flows"):
            fs = schema.to_flowsheet(schema.apply_scenario(m, sid), "SRK"); self.assertEqual(fs.streams["OUTLET"].P_kPa, None)
        self.assertAlmostEqual(schema.to_flowsheet(schema.apply_scenario(m, "flows-swapped"), "SRK").streams["INLET_1"].mass_flow_kg_h, 180000.0)


class DutyFake(EnthalpyFake):
    """Enthalpy h = T kJ/kg (any stream), mass flow of derived streams = the feed's. Heater and cooler duties are then (T_out - T_in) x mass, mirror images of each other."""
    def call(self, tool, args):
        r = FakeDwsim.call(self, tool, args)
        if tool == "dwsim_stream_get_results":
            kg_s = r["mass_flow_kg_s"] or next(o["mass_flow_kg_s"] for o in self.objects.values() if o.get("mass_flow_kg_s"))
            r = {**r, "mass_flow_kg_s": kg_s, "phases": [{"name": "Mixture", "enthalpy_kJ_kg": r["temperature_K"] - 273.15, "compounds": {}}, {"name": "Vapor", "fraction": 0.0}]}
        return r


class DutyTransport(FakeTransport):
    def __init__(self): self.fake = DutyFake()


class HeaterCooler(unittest.TestCase):
    def hc(self): return schema.load(HEATCOOL)

    def test_cases_are_valid_and_independent_values_are_consistent(self):
        for f in (HEATCOOL, CONDENSER): self.assertEqual(schema.validate(schema.load(f)), [], f)
        c = self.hc(); r = {x["name"]: x["value"] for x in c["reported"] if "value" in x}
        self.assertAlmostEqual(r["heater_duty"], -r["cooler_duty"], places=3); self.assertAlmostEqual(r["heater_duty"] / 3600, 230.135, places=2)       # kW, against the tutorial's ~230
        self.assertEqual(schema.load(CONDENSER)["source"]["read"], "computed")
        flow2 = {x["name"]: x["value"] for x in schema.apply_scenario(c, "flow-2-kg-s")["reported"] if "value" in x}; self.assertAlmostEqual(flow2["heater_duty"], 2 * r["heater_duty"], delta=1.0)
        dp = {x["name"]: x for x in schema.apply_scenario(c, "pressure-drop-100kPa")["reported"]}; self.assertAlmostEqual(dp["net_duty"]["range"][0] / dp["net_duty"]["range"][1], 340 / 327, places=3)
        self.assertAlmostEqual(dp["heater_duty"]["value"] + dp["cooler_duty"]["value"], -333.33, delta=0.1)                                                  # the band is around the independent difference

    def test_duty_sum_kind_is_validated(self):
        c = self.hc(); c["reported"][2]["targets"] = ["H", "NOPE"]; self.assertTrue(any("targets must be" in x for x in schema.validate(c)))

    def test_duties_and_their_sum_come_from_the_stream_enthalpies(self):
        run = runner.run_case(self.hc(), DutyTransport, packages=["Steam Tables"], scenarios=["base"]); v = run["results"][0]["values"]
        self.assertAlmostEqual(v["heater_duty"]["simulated"], 55 * 3600.0); self.assertAlmostEqual(v["cooler_duty"]["simulated"], -55 * 3600.0)             # (80 - 25) K x 3600 kg/h at 1 kJ/kg/K
        self.assertAlmostEqual(v["net_duty"]["simulated"], 0.0); self.assertTrue(v["net_duty"]["within_tol"])
        self.assertFalse(v["heater_duty"]["within_tol"])                                                                                                      # not the real water enthalpy, so it must not pass

    def test_heater_pressure_drop_reaches_the_server_with_the_right_sign(self):
        t = DutyTransport(); runner.run_case(self.hc(), lambda: t, packages=["Steam Tables"], scenarios=["pressure-drop-100kPa"])
        sets = {a["name"]: a["properties"] for tool, a in t.fake.calls if tool == "dwsim_unitop_set"}
        self.assertEqual(sets["H"]["CalcMode"], "OutletTemperature"); self.assertAlmostEqual(sets["H"]["OutletTemperature"], 353.15); self.assertAlmostEqual(sets["H"]["DeltaP"], 100000.0)   # a drop is positive
        self.assertAlmostEqual(sets["C"]["DeltaP"], 0.0)


FOSSEE = ["methanol-water-mixer-fossee-exp1", "water-heater-raoult-fossee-exp9", "pentane-hexane-heptane-flash-fossee-exp7"]
def _fossee(i): return schema.load(os.path.join(os.path.dirname(CASE), i + ".json"))


class Fossee(unittest.TestCase):
    """Cases built from the FOSSEE DWSIM manual (Exp 1, 7, 9). The manual's results are images, so every reference is an independent calculation; these tests check the case records themselves."""
    def test_all_validate_and_cite_the_manual(self):
        for i in FOSSEE:
            c = _fossee(i); self.assertEqual(schema.validate(c), [], i)
            self.assertIn("fossee.in", c["source"]["url"]); self.assertEqual(c["basis"]["package_in_paper"], "Raoult's Law"); self.assertFalse(c["review"]["human"])

    def test_mixer_reference_is_the_mole_balance(self):
        c = _fossee(FOSSEE[0]); mm = c["basis"]["molar_mass_g_mol"]; f = {s["id"]: s for s in c["streams"]}
        kmol = lambda s: s["mass_flow"]["value"] / sum(x * mm[k] for k, x in s["composition"]["values"].items())
        self.assertAlmostEqual(kmol(f["INLET_1"]), 20, delta=1e-3); self.assertAlmostEqual(kmol(f["INLET_2"]), 10, delta=1e-3)
        r = {x["name"]: x["value"] for x in c["reported"]}
        self.assertAlmostEqual(r["outlet_mass"], f["INLET_1"]["mass_flow"]["value"] + f["INLET_2"]["mass_flow"]["value"], delta=1e-3)
        self.assertAlmostEqual(r["outlet_methanol_mass_fraction"], 10 * mm["Methanol"] / r["outlet_mass"], places=5)

    def test_flash_reference_satisfies_its_own_balances(self):
        c = _fossee(FOSSEE[2]); r = {x["name"]: x["value"] for x in c["reported"]}; mm = c["basis"]["molar_mass_g_mol"]
        self.assertAlmostEqual(r["vapor_mass_flow"] + r["liquid_mass_flow"], r["outlet_mass_sum"], delta=0.05)     # a transcription slip in either flow breaks this
        z = c["streams"][0]["composition"]["values"]; ideal = 100 * sum(x * mm[k] for k, x in z.items())
        self.assertAlmostEqual(c["streams"][0]["mass_flow"]["value"], ideal, delta=0.01)
        wf = z["N-pentane"] * mm["N-pentane"] / sum(x * mm[k] for k, x in z.items())     # component balance on pentane
        self.assertAlmostEqual(r["vapor_pentane_mass_fraction"] * r["vapor_mass_flow"] + r["liquid_pentane_mass_fraction"] * r["liquid_mass_flow"], wf * r["outlet_mass_sum"], delta=2.0)

    def test_flash_scenarios_cover_dew_and_bubble(self):
        c = _fossee(FOSSEE[2])
        for sid, field, value in (("below-dew-pressure", "P", 70.0), ("above-dew-temperature", "T", 80.0), ("above-bubble-pressure", "P", 140.0)):
            s = schema.apply_scenario(c, sid); self.assertEqual(schema.validate(s), [], sid); self.assertEqual(s["streams"][0][field]["value"], value)

    def test_heater_tolerance_was_fixed_before_the_run(self):
        c = _fossee(FOSSEE[1]); self.assertEqual(c["tolerance"]["pass_rel"], 0.01); self.assertIn("fixed before the run", c["tolerance"]["note"])


class Ledger(unittest.TestCase):
    def test_append_and_read_are_additive(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "ledger.jsonl"); self.assertEqual(ledger.read(p), [])
            self.assertEqual(ledger.append([{"case": "a"}, {"case": "b"}], p), 2); self.assertEqual(ledger.append([{"case": "c"}], p), 1)
            rows = ledger.read(p); self.assertEqual([r["case"] for r in rows], ["a", "b", "c"]); self.assertTrue(all("ts" in r for r in rows))

    def test_rows_carry_scenario_and_hash(self):
        c = case(); rows = runner.ledger_rows(runner.run_case(c, FakeTransport))
        self.assertEqual(len(rows), 9); self.assertEqual({r["scenario"] for r in rows}, {"base", "propylene-0.00571", "mass-from-mole-flow"})
        self.assertEqual({r["case_hash"] for r in rows}, {schema.case_hash(c)})


class Tools(unittest.TestCase):
    def test_registered_list_validate_and_run_gated(self):
        names = {t["name"] for t in M.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertTrue({"casebook_list", "casebook_validate", "casebook_run"} <= names)
        err, r = call("casebook_list"); self.assertFalse(err); self.assertIn("cumene-alkylator-feed-heater", [x["id"] for x in r["cases"]])
        err, r = call("casebook_validate", case_id="cumene-alkylator-feed-heater"); self.assertFalse(err); self.assertTrue(r["valid"])
        for bad in ("../etc/passwd", "Cumene", "a b"):
            err, msg = call("casebook_validate", case_id=bad); self.assertTrue(err, bad); self.assertIn("case_id must be", msg)      # refused by the id rule, not merely "file not found"
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CASEBOOK_DIR": os.path.join(d, "cases")}):
            os.makedirs(os.path.join(d, "cases")); shutil.copy(CASE, os.path.join(d, "secret.json"))          # a real case file one level above the case directory
            err, msg = call("casebook_validate", case_id="../secret"); self.assertTrue(err); self.assertIn("case_id must be", msg)
        with mock.patch.dict(os.environ):
            os.environ.pop("DWSIM_MCP_CMD", None)
            err, msg = call("casebook_run", case_id="cumene-alkylator-feed-heater"); self.assertTrue(err); self.assertIn("DWSIM_MCP_CMD", msg)

    def test_run_writes_the_ledger_only_with_confirm(self):
        with tempfile.TemporaryDirectory() as d:
            orig, old = ledger.DEFAULT, runner.default_transport
            ledger.DEFAULT = os.path.join(d, "l.jsonl"); runner.default_transport = FakeTransport
            try:
                err, r = call("casebook_run", case_id="cumene-alkylator-feed-heater", packages=["SRK"], scenarios=["base"]); self.assertFalse(err, r)
                self.assertIn("not written", r["ledger"]); self.assertEqual(ledger.read(), [])
                err, r = call("casebook_run", case_id="cumene-alkylator-feed-heater", packages=["SRK"], scenarios=["base"], confirm=True); self.assertFalse(err, r)
                self.assertEqual(r["ledger_rows_written"], 1); self.assertEqual(len(ledger.read()), 1)
            finally:
                ledger.DEFAULT, runner.default_transport = orig, old


if __name__ == "__main__": unittest.main()
