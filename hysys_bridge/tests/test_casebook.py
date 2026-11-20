import copy, json, os, shutil, tempfile, unittest
from unittest import mock
from hysys_bridge import mcp_server as M
from hysys_bridge.casebook import schema, runner, ledger, diagnose
from hysys_bridge.dwsim.fake import FakeDwsim

CASE = os.path.join(os.path.dirname(__file__), "..", "..", "studies", "cases", "cumene-alkylator-feed-heater.json")


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
