import json, os, subprocess, sys, tempfile, unittest
from hysys_bridge import mcp_server as M

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample", "hmb.csv")
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def call(tool, **args):
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})["result"]
    txt = r["content"][0]["text"]
    return r["isError"], (txt if r["isError"] else json.loads(txt))


class Server(unittest.TestCase):
    def setUp(self):
        M.SESSIONS.clear(); os.environ.pop("HYSYS_LIVE", None)
        err, _ = call("load_hmb", name="h", path=SAMPLE); self.assertFalse(err)

    def test_protocol_basics(self):
        init = M.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})["result"]
        self.assertEqual(init["protocolVersion"], "2025-03-26"); self.assertIn("tools", init["capabilities"])
        names = {t["name"] for t in M.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertTrue({"load_hmb", "validate", "write_to_hysys", "export_dexpi", "reconcile"} <= names)
        self.assertIsNone(M.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(M.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})["error"]["code"], -32601)

    def test_write_is_gated(self):
        err, r = call("write_to_hysys", name="h")
        self.assertFalse(err); self.assertFalse(r["written"]); self.assertIn("confirm", r["reason"])
        err, r = call("write_to_hysys", name="h", confirm=True)
        self.assertTrue(r["written"] and r["backend"] == "mock" and r["saved"] is False and r["readback_mismatches"] == [])

    def test_live_requires_env_and_target_case(self):
        err, msg = call("write_to_hysys", name="h", confirm=True, live=True)
        self.assertTrue(err); self.assertIn("HYSYS_LIVE", msg)
        os.environ["HYSYS_LIVE"] = "1"
        err, msg = call("write_to_hysys", name="h", confirm=True, live=True)
        self.assertTrue(err); self.assertIn("case_path or use_active", msg)

    def test_validation_errors_block_write(self):
        M.SESSIONS["h"].streams["1"].composition["Water"] = 0.2
        err, r = call("write_to_hysys", name="h", confirm=True)
        self.assertFalse(r["written"]); self.assertTrue(r["errors"])

    def test_input_guards(self):
        self.assertTrue(call("load_hmb", name="x", path="/etc/passwd")[0])               # wrong type / not allowed
        self.assertTrue(call("export_dexpi", name="h", path="/tmp/x.exe")[0])
        d = tempfile.mkdtemp(); p = os.path.join(d, "o.xml")
        self.assertFalse(call("export_dexpi", name="h", path=p)[0])
        err, msg = call("export_dexpi", name="h", path=p); self.assertTrue(err); self.assertIn("overwrite", msg)
        self.assertFalse(call("export_dexpi", name="h", path=p, overwrite=True)[0])
        self.assertTrue(call("summarize", name="nope")[0])
        self.assertTrue(call("summarize", name="h", bogus=1)[0])                          # unexpected argument
        self.assertTrue(call("load_hmb", name="y")[0])                                    # neither path nor csv_text

    def test_extract_pid_needs_upload_consent(self):
        err, r = call("extract_pid", name="p", path=SAMPLE)
        self.assertFalse(err); self.assertFalse(r["extracted"]); self.assertIn("uploads", r["reason"])

    def test_pipeline_through_tools(self):
        self.assertFalse(call("normalize", name="h")[0])
        err, v = call("validate", name="h"); self.assertFalse(v["blocks_hysys_write"])
        err, plan = call("plan_specs", name="h"); self.assertEqual(plan["count"], 8)
        d = tempfile.mkdtemp(); p = os.path.join(d, "o.xml"); call("export_dexpi", name="h", path=p)
        self.assertFalse(call("load_dexpi", name="d", path=p)[0])
        err, s = call("score", name="d", truth="h"); self.assertIn("edges P/R/F1 1.00/1.00/1.00", s["score"])
        err, m = call("merge_pid_hmb", topology="d", hmb="h"); self.assertEqual(m["conflicts_and_gaps"], [])
        err, rc = call("reconcile", name="d", fix=False); self.assertFalse(err)

    def test_spreadsheet_method_and_layout_tool(self):
        err, lay = call("spreadsheet_layout", name="h", units={"T": "K"})
        self.assertFalse(err); self.assertEqual(lay["units"]["T"], "K"); self.assertTrue(lay["in"][0]["label"].endswith("|T"))
        err, bad = call("spreadsheet_layout", name="h", units={"T": "rankine"}); self.assertTrue(err)
        err, r = call("write_to_hysys", name="h", confirm=True, method="spreadsheet")
        self.assertFalse(err); self.assertEqual((r["method"], r["backend"], r["saved"]), ("spreadsheet", "mock", False))
        self.assertTrue(r["propagation_ok"]); self.assertEqual(r["propagation_failures"], [])
        err, msg = call("write_to_hysys", name="h", confirm=True, method="spreadsheet", live=True)
        self.assertTrue(err); self.assertIn("HYSYS_LIVE", msg)
        d = tempfile.mkdtemp(); p = os.path.join(d, "layout.csv")
        self.assertFalse(call("spreadsheet_layout", name="h", path=p)[0]); self.assertTrue(os.path.getsize(p) > 50)

    def test_stdio_subprocess(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
        p = subprocess.run([sys.executable, "-m", "hysys_bridge.mcp_server"], input="\n".join(map(json.dumps, msgs)) + "\nnot json\n",
                           capture_output=True, text=True, cwd=ROOT, timeout=30)
        out = [json.loads(l) for l in p.stdout.splitlines()]
        self.assertEqual(len(out), 3); self.assertEqual(out[2]["error"]["code"], -32700)
        self.assertEqual(p.stderr, "")


if __name__ == "__main__":
    unittest.main()
