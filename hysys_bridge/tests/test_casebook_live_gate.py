"""The casebook tools run on real DWSIM only: they must not start it unless the call says live=true."""
import json, os, unittest
from unittest import mock

from hysys_bridge import mcp_server as M
from hysys_bridge.casebook import hazop, ledger, runner

CASE = "water-heater-cooler-tutorial"
STUDY = "derived-water-exchanger"


def call(tool, **args):
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})["result"]
    return r["isError"], r["content"][0]["text"]


class Started(Exception):
    pass


class LiveGate(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"DWSIM_MCP_CMD": "not-a-real-simulator --stdio"})
        env.start(); self.addCleanup(env.stop)
        self.started = []

        def transport(cmd):                                  # records instead of launching a process
            self.started.append(cmd)
            raise Started("DWSIM would have been started")

        for target, name, new in ((runner, "StdioTransport", transport), (ledger, "append", mock.Mock(return_value=0))):
            p = mock.patch.object(target, name, new); p.start(); self.addCleanup(p.stop)

    def refused(self, tool, **args):
        err, text = call(tool, **args)
        self.assertEqual(self.started, [], "DWSIM was started")
        self.assertFalse(err, text)
        out = json.loads(text)
        self.assertIs(out["ran"], False)
        self.assertIn("live=true", out["reason"])
        self.assertEqual(ledger.append.call_count, 0)

    def test_run_does_not_start_dwsim_without_live(self):
        for extra in ({}, {"live": False}, {"confirm": True}):
            with self.subTest(extra):
                self.refused("casebook_run", case_id=CASE, **extra)

    def test_hazop_does_not_start_dwsim_without_live(self):
        for extra in ({}, {"live": False}):
            with self.subTest(extra):
                self.refused("casebook_hazop", spec_id=STUDY, **extra)

    def test_live_true_reaches_dwsim(self):
        for tool, args in (("casebook_run", {"case_id": CASE}), ("casebook_hazop", {"spec_id": STUDY})):
            with self.subTest(tool):
                self.started.clear()
                err, text = call(tool, live=True, **args)
                self.assertTrue(err and "would have been started" in text, text)
                self.assertEqual(self.started, [["not-a-real-simulator", "--stdio"]])

    def test_live_as_text_is_refused_before_anything_starts(self):
        err, text = call("casebook_run", case_id=CASE, live="true")
        self.assertTrue(err); self.assertIn("true or false", text); self.assertEqual(self.started, [])

    def test_live_without_the_operator_command_says_so(self):
        del os.environ["DWSIM_MCP_CMD"]
        err, text = call("casebook_run", case_id=CASE, live=True)
        self.assertTrue(err); self.assertIn("DWSIM_MCP_CMD", text)

    def test_repeated_packages_and_scenarios_do_not_repeat_simulator_runs(self):
        err, text = call("casebook_validate", case_id=CASE); self.assertFalse(err, text)
        from hysys_bridge.casebook import tools
        pk = tools._load(CASE)["basis"]["packages"][0]
        with mock.patch.object(runner, "run_case", return_value={"ran": False}) as run:
            call("casebook_run", case_id=CASE, live=True, packages=[pk, pk], scenarios=["base", "base"])
        self.assertEqual((run.call_args.kwargs["packages"], run.call_args.kwargs["scenarios"]), ([pk], ["base"]))
        with mock.patch.object(hazop, "run_study", return_value={}) as study, mock.patch.object(hazop, "render_markdown", return_value=""):
            err, text = call("casebook_hazop", spec_id=STUDY, live=True, packages=[pk, pk])
        self.assertFalse(err, text)
        self.assertEqual(study.call_args.args[0]["packages"], [pk])


if __name__ == "__main__":
    unittest.main()
