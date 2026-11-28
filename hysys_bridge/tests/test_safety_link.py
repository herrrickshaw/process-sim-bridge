import json, os, unittest
from hysys_bridge import mcp_server as M, safety_link as SL
from hysys_bridge.dwsim import tools as DT
from hysys_bridge.dwsim.tests.test_dwsim import sheet

TOOLKIT = os.path.expanduser("~/repos/process-safety-design-toolkit")


def call(tool, **args):
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})["result"]
    t = r["content"][0]["text"]; return r["isError"], (t if r["isError"] else json.loads(t))


class Safety(unittest.TestCase):
    def test_mixture_molar_mass(self):
        self.assertAlmostEqual(SL.mixture_molar_mass({"A": 0.5, "B": 0.5}, {"A": 10.0, "B": 30.0}), 15.0)
        with self.assertRaises(ValueError): SL.mixture_molar_mass({"A": 1.0}, {})

    def test_registered_and_needs_operator_path(self):
        names = {t["name"] for t in M.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertIn("safety_relief_gas", names)
        os.environ.pop("PROCESS_SAFETY_PATH", None); M.SESSIONS.clear(); DT.CASES.clear(); M.SESSIONS["s"] = sheet()
        call("dwsim_build", name="s", confirm=True)
        err, msg = call("safety_relief_gas", name="s", stream="S3", set_g_kpa=500, k=1.3, molar_masses={"Water": 18.0})
        self.assertTrue(err); self.assertIn("solve first", msg)

    @unittest.skipUnless(os.path.isdir(TOOLKIT), "process-safety-design-toolkit not found")
    def test_sizing_matches_toolkit_directly(self):
        os.environ["PROCESS_SAFETY_PATH"] = TOOLKIT; M.SESSIONS.clear(); DT.CASES.clear(); M.SESSIONS["s"] = sheet()
        call("dwsim_build", name="s", confirm=True); be = DT.CASES["s"]["be"]
        be.last_solve = {"ok": True}                                     # mock calculates nothing: stand in for a solved case
        be.read_stream = lambda sid: {"T": 80.0, "P": 480.0, "mass": 1000.0, "mol_s": 0, "mass_fractions": {"Water": 1.0}}
        err, r = call("safety_relief_gas", name="s", stream="S3", set_g_kpa=600, k=1.3, molar_masses={"Water": 18.0})
        R = SL._toolkit(); ref = R.gas_area(1000.0, 353.15, R.relieving_pressure_kpa(600), R.ATM, 18.0, 1.3, set_g_kpa=600)
        self.assertAlmostEqual(r["required_area_mm2"], ref.required_area_mm2); self.assertEqual(r["orifice"], ref.orifice)
        os.environ.pop("PROCESS_SAFETY_PATH", None)


if __name__ == "__main__":
    unittest.main()
