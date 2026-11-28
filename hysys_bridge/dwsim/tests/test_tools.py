import json, os, unittest
from hysys_bridge import mcp_server as M
from hysys_bridge.dwsim import tools as DT
from hysys_bridge.dwsim.tests.test_dwsim import sheet


def call(tool, **args):
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})["result"]
    txt = r["content"][0]["text"]
    return r["isError"], (txt if r["isError"] else json.loads(txt))


class DwsimTools(unittest.TestCase):
    def setUp(self):
        M.SESSIONS.clear(); DT.CASES.clear(); os.environ.pop("DWSIM_MCP_CMD", None)
        M.SESSIONS["s"] = sheet()

    def test_registered_in_server(self):
        names = {t["name"] for t in M.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertTrue({"dwsim_status", "dwsim_check_specs", "dwsim_build", "dwsim_solve", "dwsim_read_stream", "dwsim_close", "write_to_hysys"} <= names)

    def test_build_is_gated_and_mock_by_default(self):
        err, r = call("dwsim_build", name="s"); self.assertFalse(err); self.assertFalse(r["built"]); self.assertIn("confirm", r["reason"])
        err, r = call("dwsim_build", name="s", confirm=True)
        self.assertTrue(r["built"] and r["backend"] == "mock" and r["saved"] is False)

    def test_live_needs_operator_command(self):
        err, msg = call("dwsim_build", name="s", confirm=True, live=True)
        self.assertTrue(err); self.assertIn("DWSIM_MCP_CMD", msg)
        self.assertEqual(DT.CASES, {})

    def test_missing_specs_block_build(self):
        M.SESSIONS["s"].streams["S3"].T_C = None
        err, r = call("dwsim_build", name="s", confirm=True)
        self.assertFalse(r["built"]); self.assertTrue(any("H1" in m for m in r["missing"]))
        err, r = call("dwsim_check_specs", name="s"); self.assertFalse(r["complete"])

    def test_solve_and_read_stream_on_mock(self):
        call("dwsim_build", name="s", confirm=True)
        err, r = call("dwsim_read_stream", name="s", stream="S3"); self.assertTrue(err); self.assertIn("solve first", r)
        err, r = call("dwsim_solve", name="s"); self.assertTrue(r["solved"]); self.assertIn("skipped", r["mismatches_vs_specs"])
        err, r = call("dwsim_read_stream", name="s", stream="S3"); self.assertAlmostEqual(r["T"], 80.0)
        err, r = call("dwsim_close", name="s"); self.assertEqual(r, {"closed": "s"}); self.assertEqual(DT.CASES, {})

    def test_solve_without_build_is_an_error(self):
        err, msg = call("dwsim_solve", name="s"); self.assertTrue(err); self.assertIn("dwsim_build", msg)


@unittest.skipUnless(os.environ.get("DWSIM_MCP_LIVE") == "1", "set DWSIM_MCP_LIVE=1 to run against the real DWSIM MCP server")
class DwsimToolsLive(unittest.TestCase):
    def test_live_roundtrip_through_tools(self):
        M.SESSIONS.clear(); DT.CASES.clear(); M.SESSIONS["s"] = sheet()
        os.environ["DWSIM_MCP_CMD"] = "podman run -i --rm --network none ghcr.io/danwbr/dwsim-mcp:latest --stdio"
        try:
            err, r = call("dwsim_build", name="s", confirm=True, live=True); self.assertTrue(r["built"] and r["backend"] == "DWSIM", r)
            err, r = call("dwsim_solve", name="s"); self.assertTrue(r["solved"], r); self.assertEqual(r["mismatches_vs_specs"], [])
            err, r = call("dwsim_read_stream", name="s", stream="S3")
            self.assertAlmostEqual(r["T"], 80.0, places=3); self.assertAlmostEqual(r["P"], 480.0, places=3)
        finally:
            call("dwsim_close", name="s"); os.environ.pop("DWSIM_MCP_CMD", None)


if __name__ == "__main__":
    unittest.main()
