import json, os, unittest
from hysys_bridge import mcp_server as M
from hysys_bridge.aspen import tools as AT
from hysys_bridge.dwsim.tests.test_dwsim import sheet


def call(tool, **args):
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})["result"]
    txt = r["content"][0]["text"]
    return r["isError"], (txt if r["isError"] else json.loads(txt))


class AspenTools(unittest.TestCase):
    def setUp(self):
        M.SESSIONS.clear(); AT.CASES.clear(); os.environ.pop("ASPEN_MODEL_PATH", None); M.SESSIONS["s"] = sheet()

    def test_registered(self):
        names = {t["name"] for t in M.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertTrue({"aspen_status", "aspen_check_specs", "aspen_build", "aspen_run", "aspen_read_stream", "aspen_close", "dwsim_build"} <= names)

    def test_build_gated_then_mock(self):
        err, r = call("aspen_build", name="s"); self.assertFalse(r["built"]); self.assertIn("confirm", r["reason"])
        err, r = call("aspen_build", name="s", confirm=True)
        self.assertTrue(r["built"] and r["backend"] == "mock" and r["saved"] is False and r["not_ok"] == [])

    def test_live_needs_operator_path(self):
        err, msg = call("aspen_build", name="s", confirm=True, live=True)
        self.assertTrue(err); self.assertIn("ASPEN_MODEL_PATH", msg); self.assertEqual(AT.CASES, {})

    def test_missing_specs_block_build(self):
        M.SESSIONS["s"].streams["S3"].T_C = None
        err, r = call("aspen_build", name="s", confirm=True)
        self.assertFalse(r["built"]); self.assertTrue(r["missing"])

    def test_unverified_unit_refused_then_allowed(self):
        M.SESSIONS["s"].units["P1"].type = "valve"
        err, r = call("aspen_build", name="s", confirm=True); self.assertFalse(r["built"]); self.assertIn("allow_unverified", r["reason"])
        err, r = call("aspen_build", name="s", confirm=True, allow_unverified=True); self.assertTrue(r["built"])

    def test_run_read_close(self):
        call("aspen_build", name="s", confirm=True)
        err, r = call("aspen_read_stream", name="s", stream="S3"); self.assertTrue(err); self.assertIn("run first", r)
        err, r = call("aspen_run", name="s"); self.assertTrue(r["solved"]); self.assertEqual(r["missing_inputs"], [])
        err, r = call("aspen_close", name="s"); self.assertEqual(r, {"closed": "s"})

    def test_run_without_build_is_an_error(self):
        err, msg = call("aspen_run", name="s"); self.assertTrue(err); self.assertIn("aspen_build", msg)


if __name__ == "__main__":
    unittest.main()
