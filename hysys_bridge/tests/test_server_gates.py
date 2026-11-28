"""The server as it is really started, the boolean gates, and the report adapter's overwrite protection."""
import json, os, subprocess, sys, tempfile, types, unittest
from unittest import mock

from hysys_bridge import extract_hmb, hmb_report_link as L, mcp_server as M

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OPERATOR_ENV = ("DWSIM_MCP_CMD", "HYSYS_LIVE", "ASPEN_MODEL_PATH", "ANTHROPIC_API_KEY")


def msg(i, method, **params):
    return {"jsonrpc": "2.0", "id": i, "method": method, "params": params}


def serve(*messages):
    """Start the server the documented way (`python -m hysys_bridge.mcp_server`) and talk to it over stdio."""
    env = {k: v for k, v in os.environ.items() if k not in OPERATOR_ENV}
    env["PYTHONPATH"] = ROOT
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory() as cwd:
        p = subprocess.run([sys.executable, "-m", "hysys_bridge.mcp_server"], input="".join(json.dumps(m) + "\n" for m in messages),
                           capture_output=True, text=True, cwd=cwd, env=env, timeout=60)
    replies = [json.loads(line) for line in p.stdout.splitlines() if line.strip()]
    return {r["id"]: r for r in replies}


class StartedAsDocumented(unittest.TestCase):
    def test_offers_every_tool_the_imported_module_has(self):
        over_stdio = {t["name"] for t in serve(msg(1, "tools/list"))[1]["result"]["tools"]}
        imported = {t["name"] for t in M.handle(msg(1, "tools/list"))["result"]["tools"]}
        self.assertEqual(sorted(imported - over_stdio), [])

    def test_a_loaded_session_is_visible_to_tools_in_other_modules(self):
        load = msg(1, "tools/call", name="load_hmb", arguments={"name": "s", "csv_text": "stream,T (C),P (kPa),mass flow (kg/h)\n1,25,101.3,100\n"})
        checks = [msg(i, "tools/call", name=n, arguments={"name": "s"}) for i, n in ((2, "dwsim_check_specs"), (3, "aspen_check_specs"))]
        got = serve(load, *checks)
        self.assertFalse(got[1]["result"]["isError"], got[1])
        for i in (2, 3):
            self.assertNotIn("no session", got[i]["result"]["content"][0]["text"])


class BooleanGates(unittest.TestCase):
    FLAGS = [(name, flag) for name, (_, _, schema) in M.TOOLS.items()
             for flag, spec in schema["properties"].items() if spec.get("type") == "boolean"]

    def call_with_spy(self, name, flag, value):
        """The real handler is replaced by a recorder, so nothing can be built, written or uploaded."""
        _, doc, schema = M.TOOLS[name]
        seen = []
        args = {k: "x" for k in schema["required"]}
        args[flag] = value
        if name == "load_hmb": args["csv_text"] = "x"
        with mock.patch.dict(M.TOOLS, {name: (lambda a: seen.append(a) or {}, doc, schema)}):
            result = M.handle(msg(1, "tools/call", name=name, arguments=args))["result"]
        return seen, result

    def test_the_sweep_covers_the_write_live_upload_and_overwrite_gates(self):
        self.assertLessEqual({("write_to_hysys", "confirm"), ("write_to_hysys", "live"), ("extract_pid", "confirm_upload"),
                              ("dwsim_build", "confirm"), ("aspen_build", "allow_unverified"), ("safety_hmb_report", "overwrite"),
                              ("casebook_run", "confirm")}, set(self.FLAGS))

    def test_text_numbers_and_null_never_reach_a_tool(self):
        for name, flag in self.FLAGS:
            for value in ("false", "no", "true", 0, 1, None):
                with self.subTest(tool=name, flag=flag, value=value):
                    seen, result = self.call_with_spy(name, flag, value)
                    self.assertEqual(seen, [])
                    self.assertTrue(result["isError"])
                    self.assertIn("true or false", result["content"][0]["text"])
                    self.assertIn(flag, result["content"][0]["text"])

    def test_real_booleans_reach_the_tool(self):
        for name, flag in self.FLAGS:
            for value in (True, False):
                with self.subTest(tool=name, flag=flag, value=value):
                    seen, result = self.call_with_spy(name, flag, value)
                    self.assertFalse(result["isError"], result)
                    self.assertIs(seen[0][flag], value)


NAMES = ("_report.xlsx", "_report.html", "_findings.csv", "_report.txt", "_added_later.json")


def fake_toolkit(module):
    """Stands in for the toolkit so these run without it. It writes more files than the adapter has ever heard of."""
    def write(result, prefix):
        files = [prefix + n for n in NAMES]
        for f in files:
            with open(f, "w", encoding="utf-8") as fh: fh.write("new report")
        return files
    audit = lambda spec: {"verdict": "pass", "counts": {}, "findings": [], "notes": [], "limits": ""}
    return types.SimpleNamespace(audit=audit, write=write)


class ReportOverwrite(unittest.TestCase):
    def run_build(self, out, overwrite=False):
        fs = extract_hmb.from_csv(os.path.join(ROOT, "hysys_bridge", "sample", "hmb.csv"))
        with mock.patch.object(L, "_module", fake_toolkit):
            return L.build(fs, None, None, None, out, overwrite)

    def read(self, path):
        with open(path, encoding="utf-8") as fh: return fh.read()

    def test_any_existing_output_file_stops_the_whole_write(self):
        for name in NAMES:
            with self.subTest(existing=name), tempfile.TemporaryDirectory() as out:
                mine = os.path.join(out, "hmb" + name)
                with open(mine, "w", encoding="utf-8") as fh: fh.write("mine")
                with self.assertRaises(FileExistsError):
                    self.run_build(out)
                self.assertEqual(self.read(mine), "mine")
                self.assertEqual(os.listdir(out), ["hmb" + name])

    def test_overwrite_true_replaces_it(self):
        with tempfile.TemporaryDirectory() as out:
            mine = os.path.join(out, "hmb_report.txt")
            with open(mine, "w", encoding="utf-8") as fh: fh.write("mine")
            self.run_build(out, overwrite=True)
            self.assertEqual(self.read(mine), "new report")

    def test_a_new_folder_gets_every_file_and_returns_their_final_paths(self):
        with tempfile.TemporaryDirectory() as top:
            out = os.path.join(top, "a", "b")
            files = self.run_build(out)["files"]
            self.assertEqual(files, [os.path.join(out, "hmb" + n) for n in NAMES])
            self.assertTrue(all(self.read(f) == "new report" for f in files))

    def test_a_link_pointing_nowhere_counts_as_existing(self):
        with tempfile.TemporaryDirectory() as out:
            os.symlink(os.path.join(out, "missing"), os.path.join(out, "hmb_report.txt"))
            with self.assertRaises(FileExistsError):
                self.run_build(out)


if __name__ == "__main__":
    unittest.main()
