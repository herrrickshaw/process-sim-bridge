"""A simulator case belongs to the session contents it was built from. Change the session and its results must not be used."""
import copy, json, os, tempfile, unittest

from hysys_bridge import mcp_server as M
from hysys_bridge.aspen import tools as AT
from hysys_bridge.dwsim import tools as DT
from hysys_bridge.dwsim.tests.test_dwsim import sheet

STALE = "changed since"

# every tool that solves a built case or uses its results, with arguments good enough to reach the case lookup
DWSIM_USERS = {
    "dwsim_solve": {},
    "dwsim_read_stream": {"stream": "F1"},
    "safety_relief_gas": {"stream": "F1", "set_g_kpa": 1000, "k": 1.3, "molar_masses": {"Water": 18.0}},
    "safety_flare_radiation": {"stream": "F1", "molar_masses": {"Water": 18.0}, "lhv_MJ_kg": 50.0},
    "lng_cost_from_stream": {"stream": "F1", "on_stream_fraction": 0.9, "stream_is_lng_product": True},
    "refinery_session_duty": {},
}
ASPEN_USERS = {"aspen_run": {}, "aspen_read_stream": {"stream": "F1"}}


def call(tool, **args):
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})["result"]
    return r["isError"], r["content"][0]["text"]


def bigger_feed():
    fs = sheet()
    fs.streams["F1"].mass_flow_kg_h = 10000.0
    return fs


class Base(unittest.TestCase):
    def setUp(self):
        saved = {k: os.environ.pop(k, None) for k in ("DWSIM_MCP_CMD", "ASPEN_MODEL_PATH")}
        self.addCleanup(lambda: os.environ.update({k: v for k, v in saved.items() if v is not None}))
        for store in (M.SESSIONS, DT.CASES, AT.CASES):
            store.clear(); self.addCleanup(store.clear)
        M.SESSIONS["s"] = sheet()
        self.build("dwsim_build"); self.build("aspen_build")
        self.assertFalse(call("dwsim_solve", name="s")[0]); self.assertFalse(call("aspen_run", name="s")[0])

    def build(self, tool):
        err, text = call(tool, name="s", confirm=True)
        self.assertTrue(not err and json.loads(text)["built"], text)

    def assert_all_refused(self, users):
        for tool, args in users.items():
            with self.subTest(tool=tool):
                err, text = call(tool, name="s", **args)
                self.assertTrue(err, text)
                self.assertIn(STALE, text)
                self.assertIn("build", text)


class ChangedSession(Base):
    def test_replacing_the_session_refuses_every_dwsim_and_aspen_user(self):
        M.SESSIONS["s"] = bigger_feed()
        self.assert_all_refused(DWSIM_USERS)
        self.assert_all_refused(ASPEN_USERS)

    def test_editing_the_session_in_place_refuses_too(self):
        edits = {"feed flow": lambda fs: setattr(fs.streams["F1"], "mass_flow_kg_h", 10000.0),
                 "composition": lambda fs: fs.streams["F1"].composition.update(Water=0.5),
                 "outlet spec": lambda fs: setattr(fs.streams["S3"], "T_C", 90.0),
                 "unit type": lambda fs: setattr(fs.units["H1"], "type", "cooler"),
                 "unit parameter": lambda fs: fs.units["H1"].params.update(duty=1.0),
                 "property package": lambda fs: setattr(fs, "fluid_package", "NRTL")}
        for what, edit in edits.items():
            with self.subTest(what):
                M.SESSIONS["s"] = sheet(); self.build("dwsim_build"); self.build("aspen_build")
                edit(M.SESSIONS["s"])
                for tool in ("dwsim_read_stream", "aspen_read_stream"):
                    self.assertIn(STALE, call(tool, name="s", stream="F1")[1])

    def test_loading_through_the_real_tool_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "v2.json"); bigger_feed().to_json(path)
            self.assertFalse(call("load_flowsheet_json", name="s", path=path)[0])
        self.assert_all_refused(DWSIM_USERS)

    def test_a_removed_session_refuses(self):
        del M.SESSIONS["s"]
        self.assert_all_refused(DWSIM_USERS)
        self.assert_all_refused(ASPEN_USERS)

    def test_a_dry_plan_or_blocked_rebuild_does_not_revive_old_results(self):
        M.SESSIONS["s"] = bigger_feed()
        self.assertIn("confirm", call("dwsim_build", name="s")[1])
        self.assert_all_refused(DWSIM_USERS)
        M.SESSIONS["s"].streams["F1"].T_C = None
        self.assertIn('"built": false', call("dwsim_build", name="s", confirm=True)[1])
        self.assertIn('"built": false', call("aspen_build", name="s", confirm=True)[1])
        self.assert_all_refused(DWSIM_USERS)
        self.assert_all_refused(ASPEN_USERS)

    def test_rebuilding_and_solving_gives_the_new_value(self):
        M.SESSIONS["s"] = bigger_feed()
        self.build("dwsim_build")
        self.assertIn("solve first", call("dwsim_read_stream", name="s", stream="F1")[1])
        self.assertFalse(call("dwsim_solve", name="s")[0])
        self.assertAlmostEqual(json.loads(call("dwsim_read_stream", name="s", stream="F1")[1])["mass"], 10000.0)

    def test_an_out_of_date_case_can_still_be_closed(self):
        M.SESSIONS["s"] = bigger_feed()
        for tool, store in (("dwsim_close", DT.CASES), ("aspen_close", AT.CASES)):
            self.assertFalse(call(tool, name="s")[0])
            self.assertNotIn("s", store)


class UnchangedSession(Base):
    def assert_still_usable(self):
        for tool in ("dwsim_read_stream", "aspen_read_stream"):
            err, text = call(tool, name="s", stream="F1")
            self.assertFalse(err, text)

    def test_read_only_tools_keep_the_results(self):
        for tool in ("summarize", "validate", "plan_specs", "dwsim_check_specs", "aspen_check_specs", "export_dexpi"):
            with self.subTest(tool):
                with tempfile.TemporaryDirectory() as d:
                    extra = {"path": os.path.join(d, "x.xml")} if tool == "export_dexpi" else {}
                    err, text = call(tool, name="s", **extra)
                    self.assertFalse(err, text)
                self.assert_still_usable()

    def test_reloading_identical_contents_keeps_the_results(self):
        M.SESSIONS["s"] = copy.deepcopy(M.SESSIONS["s"])
        self.assert_still_usable()

    def test_changing_back_makes_the_matching_results_usable_again(self):
        M.SESSIONS["s"] = bigger_feed()
        M.SESSIONS["s"] = sheet()
        self.assert_still_usable()


if __name__ == "__main__":
    unittest.main()
