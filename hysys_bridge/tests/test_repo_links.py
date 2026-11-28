import json, os, shutil, sys, tempfile, unittest
from unittest import mock
from hysys_bridge import lng_link as L, ppac_link as P, safety_link as SL, mcp_server as M
from hysys_bridge.dwsim import tools as DT
from hysys_bridge.dwsim.tests.test_dwsim import sheet

TOOLKIT = os.path.expanduser("~/repos/process-safety-design-toolkit")
FAKE_LNG = '''
import dataclasses
@dataclasses.dataclass
class LiquefactionInputs:
    capacity_mtpa: float = 5.0
    capex_per_tpa: float = 900.0
    life_years: int = 20
@dataclasses.dataclass
class ShippingInputs:
    distance_nm: float = 5000.0
@dataclasses.dataclass
class RegasInputs:
    capacity_mtpa: float = 5.0
@dataclasses.dataclass
class Estimate:
    feed_gas: float; fob_price: float; shipping: float; regas: float; delivered: float; liquefaction_capex_usd: float; detail: dict
def estimate(liq=None, ship=None, regas=None):
    liq, ship, regas = liq or LiquefactionInputs(), ship or ShippingInputs(), regas or RegasInputs()
    return Estimate(1.0, liq.capex_per_tpa / 1000, ship.distance_nm / 1000, regas.capacity_mtpa / 10, liq.capex_per_tpa / 1000 + ship.distance_nm / 1000 + regas.capacity_mtpa / 10, liq.capex_per_tpa * liq.capacity_mtpa * 1e6,
                    {"liquefaction": dataclasses.asdict(liq), "shipping": dataclasses.asdict(ship), "regas": dataclasses.asdict(regas)})
'''


def solved(mass=1.0e6):
    M.SESSIONS.clear(); DT.CASES.clear(); M.SESSIONS["s"] = sheet(); M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "dwsim_build", "arguments": {"name": "s", "confirm": True}}})
    be = DT.CASES["s"]["be"]; be.last_solve = {"ok": True}
    be.read_stream = lambda sid: {"T": 80.0, "P": 480.0, "mass": mass, "mol_s": 0, "mass_fractions": {"Methane": 1.0}}


class Lng(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); os.makedirs(os.path.join(self.d, "lng_cost")); open(os.path.join(self.d, "lng_cost", "__init__.py"), "w").write(FAKE_LNG)
        self.env = mock.patch.dict(os.environ, {"LNG_COST_PATH": self.d}); self.env.start()
        for m in [k for k in sys.modules if k == "lng_cost"]: del sys.modules[m]

    def tearDown(self): self.env.stop(); shutil.rmtree(self.d); sys.modules.pop("lng_cost", None); sys.path[:] = [p for p in sys.path if p != self.d]

    def test_estimate_lists_defaults_and_warns(self):
        r = L.t_estimate({"liquefaction": {"capex_per_tpa": 1000}, "shipping": {"distance_nm": 9000}})
        self.assertAlmostEqual(r["delivered"], 1.0 + 9.0 + 0.5); self.assertIn("placeholders", r["warning"])
        self.assertIsInstance(L.t_estimate({"liquefaction": {"life_years": 25}})["inputs"]["liquefaction"]["life_years"], int)
        self.assertEqual(r["defaults_used"]["liquefaction"], ["capacity_mtpa", "life_years"]); self.assertEqual(r["defaults_used"]["shipping"], []); self.assertEqual(r["defaults_used"]["regas"], ["capacity_mtpa"])

    def test_unknown_inputs_and_bad_shapes_refused(self):
        with self.assertRaisesRegex(ValueError, "unknown input"): L.t_estimate({"shipping": {"distanse_nm": 1}})
        with self.assertRaisesRegex(ValueError, "must be an object"): L.t_estimate({"regas": [1]})

    def test_path_is_operator_set_only(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LNG_COST_PATH")
            with self.assertRaises(PermissionError): L.t_estimate({})
        self.assertNotIn("path", json.dumps(M.TOOLS["lng_cost_estimate"][2]))

    def test_capacity_arithmetic(self):
        self.assertAlmostEqual(L.capacity_mtpa_from_stream(1.0e6, 0.9), 1.0e6 * 8760 * 0.9 / 1e9)
        for bad in ((0, 0.9), (1e6, 0), (1e6, 1.1), (-5, 0.5)):
            with self.assertRaises(ValueError): L.capacity_mtpa_from_stream(*bad)

    def test_from_stream_uses_the_solved_flow_and_demands_the_statements(self):
        solved(1.0e6); r = L.t_from_stream({"name": "s", "stream": "S3", "on_stream_fraction": 0.9, "stream_is_lng_product": True, "liquefaction": {"capex_per_tpa": 1000}})
        cap = 1.0e6 * 8760 * 0.9 / 1e9; self.assertAlmostEqual(r["capacity_from_stream"]["capacity_mtpa"], cap); self.assertAlmostEqual(r["inputs"]["liquefaction"]["capacity_mtpa"], cap)
        self.assertNotIn("capacity_mtpa", r["defaults_used"]["liquefaction"])
        base = {"name": "s", "stream": "S3", "on_stream_fraction": 0.9, "stream_is_lng_product": True}
        with self.assertRaisesRegex(ValueError, "stream_is_lng_product"): L.t_from_stream({**base, "stream_is_lng_product": False})
        with self.assertRaisesRegex(ValueError, "on_stream_fraction"): L.t_from_stream({k: v for k, v in base.items() if k != "on_stream_fraction"})
        with self.assertRaisesRegex(ValueError, "taken from the stream"): L.t_from_stream({**base, "liquefaction": {"capacity_mtpa": 3}})
        DT.CASES["s"]["be"].last_solve = {"ok": False}
        with self.assertRaisesRegex(RuntimeError, "solve first"): L.t_from_stream(base)


class Ppac(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); os.makedirs(os.path.join(self.d, "csv"))
        open(os.path.join(self.d, "index.csv"), "w").write("table_no,caption,page,csv_file,rows,cols,flag\n,(continuation),4,csv/c.csv,1,1,ok\n4.1,Refineries:InstalledCapacity and Crude Oil Processing,47,csv/t41.csv,5,4,ok\n4.2,Refineries second table,48,csv/t41.csv,5,4,ok\n4.3,Refineries third table,49,csv/t41.csv,5,4,ok\n9.9,Other table,60,csv/../../escape.csv,1,1,ok\n")
        open(os.path.join(self.d, "csv", "t41.csv"), "w").write("Table 4.1 : x,,,\nSr. No.,Refinery,Installed capacity (MMTPA),Processing\n,,01.04.2025,2024-25\n1,Mathura,8.0,\"8,100.5\"\n2,Mathura,9.0,n.a.\n3,Haldia,8.0,6.9\n")
        self.env = mock.patch.dict(os.environ, {"PPAC_DATA_PATH": self.d}); self.env.start()

    def tearDown(self): self.env.stop(); shutil.rmtree(self.d)

    def test_search_matches_caption_words_ignoring_spacing_and_skips_unnumbered(self):
        r = P.t_search({"query": "refineries installedcapacity"}); self.assertEqual([m["table_no"] for m in r["matches"]], ["4.1"]); self.assertIn("check the cell", r["caveat"])
        self.assertEqual(P.t_search({"query": "crude oil"})["total_matches"], 1); self.assertEqual(P.t_search({"query": "continuation"})["total_matches"], 0); self.assertEqual(P.t_search({"query": "refineries zzz"})["total_matches"], 0)
        lim = P.t_search({"query": "refineries", "limit": 1}); self.assertEqual((len(lim["matches"]), lim["total_matches"]), (1, 3)); self.assertEqual(P.t_search({"query": "nothing like this"})["matches"], [])
        with self.assertRaises(ValueError): P.t_search({"query": " "})

    def test_table_returns_raw_rows_with_indices(self):
        r = P.t_table({"table_no": "4.1"}); self.assertEqual(r["rows"][3]["cells"], ["1", "Mathura", "8.0", "8,100.5"]); self.assertEqual(r["rows"][3]["row"], 3)
        self.assertTrue(P.t_table({"table_no": "4.1", "limit": 2})["truncated"])
        with self.assertRaises(KeyError): P.t_table({"table_no": "7.7"})

    def test_compare_reports_the_difference_and_refuses_ambiguity(self):
        r = P.t_compare({"table_no": "4.1", "row_label": "Haldia", "col": 2, "model_value": 8.4, "unit_note": "MMTPA"})
        self.assertAlmostEqual(r["difference"], 0.4); self.assertAlmostEqual(r["difference_pct_of_published"], 5.0); self.assertEqual(r["published_cell"], "8.0"); self.assertEqual(r["unit_stated_by_caller"], "MMTPA")
        with self.assertRaisesRegex(ValueError, "matches 2 rows"): P.t_compare({"table_no": "4.1", "row_label": "Mathura", "col": 2, "model_value": 1, "unit_note": "u"})
        with self.assertRaisesRegex(ValueError, "matches 0 rows"): P.t_compare({"table_no": "4.1", "row_label": "Nowhere", "col": 2, "model_value": 1, "unit_note": "u"})
        for lab in ("Hald", "6.9", "haldia refinery"):
            with self.assertRaisesRegex(ValueError, "matches 0 rows"): P.t_compare({"table_no": "4.1", "row_label": lab, "col": 2, "model_value": 1, "unit_note": "u"})
        self.assertEqual(P.t_compare({"table_no": "4.1", "row_label": "HALDIA", "col": 2, "model_value": 1, "unit_note": "u"})["row"], 5)         # case-insensitive exact match
        with self.assertRaisesRegex(ValueError, "outside the row"): P.t_compare({"table_no": "4.1", "row_label": "Haldia", "col": -1, "model_value": 1, "unit_note": "u"})
        with self.assertRaisesRegex(ValueError, "outside the row"): P.t_compare({"table_no": "4.1", "row_label": "Haldia", "col": 9, "model_value": 1, "unit_note": "u"})
        for k in ("unit_note", "row_label", "model_value", "col", "table_no"):
            a = {"table_no": "4.1", "row_label": "Haldia", "col": 2, "model_value": 1, "unit_note": "u"}; del a[k]
            with self.assertRaisesRegex(ValueError, f"{k} is required"): P.t_compare(a)

    def test_numbers_with_thousands_separators_and_text_cells(self):
        self.assertEqual(P.number("8,100.5"), 8100.5); self.assertEqual(P.number(" -3 "), -3.0)
        for bad in ("n.a.", "", "1e3", "8.0%", "1,2,x"):
            with self.assertRaises(ValueError): P.number(bad)

    def test_zero_published_value_gives_no_percentage(self):
        open(os.path.join(self.d, "csv", "t41.csv"), "a").write("4,Zeroville,0,0\n")
        self.assertIsNone(P.t_compare({"table_no": "4.1", "row_label": "Zeroville", "col": 2, "model_value": 1, "unit_note": "u"})["difference_pct_of_published"])

    def test_csv_path_cannot_leave_the_data_folder(self):
        with self.assertRaisesRegex(ValueError, "escapes"): P.t_table({"table_no": "9.9"})

    def test_data_folder_is_operator_set_and_may_be_the_repo_or_the_subfolder(self):
        os.environ.pop("PPAC_DATA_PATH")
        with self.assertRaises(PermissionError): P.t_search({"query": "x"})
        parent = tempfile.mkdtemp(); shutil.copytree(self.d, os.path.join(parent, "annual_fy2025-26_h1"))
        with mock.patch.dict(os.environ, {"PPAC_DATA_PATH": parent}): self.assertEqual(P.t_search({"query": "refineries"})["total_matches"], 3)
        shutil.rmtree(parent)
        with mock.patch.dict(os.environ, {"PPAC_DATA_PATH": tempfile.gettempdir() + "/no-such-ppac"}), self.assertRaises(FileNotFoundError): P.t_search({"query": "x"})
        self.assertNotIn("path", json.dumps(M.TOOLS["ppac_search"][2]))


@unittest.skipUnless(os.path.isdir(TOOLKIT), "process-safety-design-toolkit not found")
class SafetyMore(unittest.TestCase):
    def setUp(self): self.env = mock.patch.dict(os.environ, {"PROCESS_SAFETY_PATH": TOOLKIT}); self.env.start()
    def tearDown(self): self.env.stop()

    def test_lopa_matches_hand_arithmetic_and_defaults_nothing(self):
        r = SL.t_lopa({"initiating_freq_per_yr": 0.1, "ipl_pfds": [0.1, 0.01], "tolerable_per_yr": 1e-5})["lopa"]
        self.assertAlmostEqual(r["mitigated_per_yr"], 1e-4); self.assertAlmostEqual(r["required_sif_pfd"], 0.1); self.assertAlmostEqual(r["required_rrf"], 10.0); self.assertFalse(r["meets_target_without_sif"])
        self.assertTrue(SL.t_lopa({"initiating_freq_per_yr": 0.1, "ipl_pfds": [0.01], "tolerable_per_yr": 1e-2})["lopa"]["meets_target_without_sif"])
        for k in ("initiating_freq_per_yr", "tolerable_per_yr"):
            a = {"initiating_freq_per_yr": 0.1, "ipl_pfds": [0.1], "tolerable_per_yr": 1e-5}; del a[k]
            with self.assertRaisesRegex(ValueError, f"{k} is required"): SL.t_lopa(a)
        for bad in (None, "x", [0.1, 2], [0], [True and "a"]):
            with self.assertRaises(ValueError): SL.t_lopa({"initiating_freq_per_yr": 0.1, "ipl_pfds": bad, "tolerable_per_yr": 1e-5})
        out = SL.t_lopa({"initiating_freq_per_yr": 0.1, "ipl_pfds": [], "tolerable_per_yr": 1e-5}); self.assertAlmostEqual(out["lopa"]["mitigated_per_yr"], 0.1); self.assertIn("not applied", out["reference_only"]["note"])

    def test_conditional_modifiers_positive_inputs_and_the_equality_boundary(self):
        self.assertAlmostEqual(SL.t_lopa({"initiating_freq_per_yr": 0.1, "ipl_pfds": [0.1], "tolerable_per_yr": 1e-5, "conditional_modifiers": 0.5})["lopa"]["mitigated_per_yr"], 5e-3)
        with self.assertRaisesRegex(ValueError, "must be positive"): SL.t_lopa({"initiating_freq_per_yr": 0, "ipl_pfds": [0.1], "tolerable_per_yr": 1e-5})
        a = {"initiating_freq_per_yr": 0.1, "ipl_pfds": [0.1, 0.01], "tolerable_per_yr": 1e-5, "sif": {"arch": "1oo1", "lambda_du_per_h": 1e-6, "proof_test_h": 8760}}
        req = SL.t_lopa(a)["lopa"]["required_sif_pfd"]
        with mock.patch.object(SL._module("sil"), "pfd_avg", return_value=req): self.assertTrue(SL.t_lopa(a)["sif"]["meets_required"])         # a SIF exactly at the required PFD meets it

    def test_sif_check_uses_the_toolkit_pfd_and_compares_with_the_requirement(self):
        S = SL._module("sil"); sif = {"arch": "1oo1", "lambda_du_per_h": 1e-6, "proof_test_h": 8760}
        r = SL.t_lopa({"initiating_freq_per_yr": 0.1, "ipl_pfds": [0.1, 0.01], "tolerable_per_yr": 1e-5, "sif": sif})["sif"]
        self.assertAlmostEqual(r["pfd_avg"], S.pfd_avg("1oo1", 1e-6, 8760)); self.assertEqual(r["meets_required"], r["pfd_avg"] <= 0.1); self.assertIn("architectural constraints", r["not_checked"])
        tight = SL.t_lopa({"initiating_freq_per_yr": 0.1, "ipl_pfds": [0.1, 0.01], "tolerable_per_yr": 1e-9, "sif": sif})["sif"]; self.assertFalse(tight["meets_required"])

    def test_lopa_label_to_a_hazop_deviation_must_exist(self):
        spec = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "studies", "hazop", "example-water-exchanger-deviations.json"))); dev = spec["nodes"][0]["deviations"][0]
        base = {"initiating_freq_per_yr": 0.1, "ipl_pfds": [0.1], "tolerable_per_yr": 1e-5, "spec_id": "example-water-exchanger-deviations"}
        h = SL.t_lopa({**base, "deviation_id": dev["id"]})["hazop_deviation"]; self.assertEqual((h["parameter"], h["guide_word"]), (dev["parameter"], dev["guide_word"])); self.assertIn("label", h["note"])
        with self.assertRaises(KeyError): SL.t_lopa({**base, "deviation_id": "no-such"})
        with self.assertRaisesRegex(ValueError, "both spec_id and deviation_id"): SL.t_lopa({**base})
        with self.assertRaises(KeyError): SL.t_lopa({**base, "spec_id": "no-such-study", "deviation_id": "x"})

    def test_flare_radiation_from_a_solved_stream(self):
        solved(3600.0)                                                                  # 1 kg/s
        r = SL.t_flare_radiation({"name": "s", "stream": "S3", "molar_masses": {"Methane": 16.04}, "lhv_MJ_kg": 50.0, "distance_m": 30.0, "flame_length_m": 20.0})
        F = SL._module("flare"); Q = 50.0e6; frac = F.radiant_fraction(16.04)
        self.assertAlmostEqual(r["heat_release_MW"], 50.0); self.assertAlmostEqual(r["radiant_fraction"], frac); self.assertAlmostEqual(r["radiation_kW_m2_at_distance"]["kW_m2"], F.radiation_kW_m2(Q, 30.0, frac))
        self.assertEqual(r["safe_distance_m_by_level"], F.radiation_checks(Q, frac, 20.0)["distance_m"]); self.assertTrue(r["warnings"])
        r2 = SL.t_flare_radiation({"name": "s", "stream": "S3", "molar_masses": {"Methane": 16.04}, "lhv_MJ_kg": 50.0, "flame_length_m": 20.0, "tau": 0.5})
        self.assertEqual(r2["safe_distance_m_by_level"], F.radiation_checks(Q, frac, 20.0, 0.5)["distance_m"]); self.assertNotEqual(r2["safe_distance_m_by_level"], r["safe_distance_m_by_level"])
        r3 = SL.t_flare_radiation({"name": "s", "stream": "S3", "molar_masses": {"Methane": 16.04}, "lhv_MJ_kg": 50.0, "distance_m": 30.0, "tau": 0.5}); self.assertAlmostEqual(r3["radiation_kW_m2_at_distance"]["kW_m2"], F.radiation_kW_m2(Q, 30.0, frac, 0.5))
        with self.assertRaisesRegex(ValueError, "lhv_MJ_kg is required"): SL.t_flare_radiation({"name": "s", "stream": "S3", "molar_masses": {"Methane": 16.04}})
        with self.assertRaisesRegex(ValueError, "molar_masses missing"): SL.t_flare_radiation({"name": "s", "stream": "S3", "molar_masses": {}, "lhv_MJ_kg": 50})
        DT.CASES["s"]["be"].last_solve = {"ok": False}
        with self.assertRaisesRegex(RuntimeError, "solve first"): SL.t_flare_radiation({"name": "s", "stream": "S3", "molar_masses": {"Methane": 16.04}, "lhv_MJ_kg": 50})


class Registered(unittest.TestCase):
    def test_tools_are_registered_and_listed(self):
        names = {t["name"] for t in M.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertTrue({"safety_lopa", "safety_flare_radiation", "lng_cost_estimate", "lng_cost_from_stream", "ppac_search", "ppac_table", "ppac_compare"} <= names)

    def test_safety_tools_need_the_operator_path(self):
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("PROCESS_SAFETY_PATH", None)
            with self.assertRaises(PermissionError): SL.t_lopa({"initiating_freq_per_yr": 0.1, "ipl_pfds": [0.1], "tolerable_per_yr": 1e-5})


if __name__ == "__main__": unittest.main()
