"""A DWSIM server that stops answering must not freeze the caller or be left running, and a closed Aspen case must close Aspen.

DWSIM is played by a small child process, Aspen's Windows libraries by fakes. Every call that could hang runs under an outer limit."""
import io, json, os, subprocess, sys, tempfile, textwrap, threading, time, types, unittest
from unittest import mock

from hysys_bridge import mcp_server as M
from hysys_bridge.aspen import backend as AB, tools as AT
from hysys_bridge.dwsim import tools as DT
from hysys_bridge.dwsim.backend import StdioTransport
from hysys_bridge.dwsim.tests.test_dwsim import sheet

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIMIT = 30                                   # seconds: far above the timeouts under test, so only a real hang reaches it
START_S = "10"                               # time allowed to start the fake (a new Python process), which can be slow on a busy machine

FAKE = textwrap.dedent('''
    import json, os, signal, subprocess, sys, time
    mode, pidfile = sys.argv[1], sys.argv[2]
    pids = [os.getpid()]
    if mode == "ignores_sigterm": signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if mode == "grandchild":                     # a wrapper whose child inherits the pipes
        pids.append(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"]).pid)
    with open(pidfile, "w") as fh: fh.write(" ".join(map(str, pids)))
    time.sleep(float(os.environ.get("FAKE_START_DELAY", "0")))
    if mode == "never_reads": time.sleep(600)
    for line in sys.stdin:
        m = json.loads(line)
        if "id" not in m: continue
        first = m["method"] == "initialize"
        if mode == "silent_start" and first: time.sleep(600)
        if mode == "refuses_start" and first:
            print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "error": {"message": "licence refused"}}), flush=True); time.sleep(600)
        if not first and mode in ("silent_call", "ignores_sigterm", "grandchild"): time.sleep(600)
        result = {} if first else {"content": [{"text": json.dumps({"flowsheet_id": "fs-1"})}]}
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": result}), flush=True)
    if mode in ("ignores_sigterm", "deaf_to_eof"): time.sleep(600)
''')


def alive(pid):
    """Running, not merely unreaped."""
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


def gone(pids, seconds=8):
    end = time.time() + seconds
    while time.time() < end:
        if not any(map(alive, pids)): return True
        time.sleep(0.1)
    return False


@unittest.skipIf(os.name == "nt", "process checks here are POSIX")
class FakeDwsim(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        self.script, self.pidfile = os.path.join(d.name, "fake.py"), os.path.join(d.name, "pids")
        with open(self.script, "w") as fh: fh.write(FAKE)
        env = mock.patch.dict(os.environ, {"DWSIM_MCP_TIMEOUT_S": "1"}); env.start(); self.addCleanup(env.stop)
        self.addCleanup(self.kill_leftovers)

    def pids(self):
        try:
            with open(self.pidfile) as fh: return [int(x) for x in fh.read().split()]
        except FileNotFoundError: return []

    def kill_leftovers(self):
        for pid in self.pids():
            try: os.kill(pid, 9)
            except OSError: pass

    def cmd(self, mode): return [sys.executable, self.script, mode, self.pidfile]

    def started(self, mode):
        """A transport that has finished starting, with the short limit applied only to what follows."""
        with mock.patch.dict(os.environ, {"DWSIM_MCP_TIMEOUT_S": START_S}):
            t, error = self.bounded(lambda: StdioTransport(self.cmd(mode)))
        self.assertIsNone(error)
        t.timeout = 1.0
        return t

    def bounded(self, fn):
        """(result, error) of fn, failing the test if it is still running after LIMIT seconds."""
        box = []
        def run():
            try: box.append((fn(), None))
            except BaseException as e: box.append((None, e))
        t = threading.Thread(target=run, daemon=True); t.start(); t.join(LIMIT)
        if t.is_alive():
            self.kill_leftovers(); t.join(5)
            self.fail(f"still waiting after {LIMIT} s: the caller is frozen")
        return box[0]


class Hangs(FakeDwsim):
    def test_a_server_that_never_answers_startup_times_out_and_is_stopped(self):
        with mock.patch.dict(os.environ, {"DWSIM_MCP_TIMEOUT_S": "5"}):
            _, error = self.bounded(lambda: StdioTransport(self.cmd("silent_start")))
        self.assertIsInstance(error, TimeoutError, error)
        self.assertTrue(self.pids(), "the fake never started, so nothing was checked")
        self.assertTrue(gone(self.pids()), "process left running")

    def test_a_server_that_refuses_startup_is_not_left_running(self):
        with mock.patch.dict(os.environ, {"DWSIM_MCP_TIMEOUT_S": START_S}):
            _, error = self.bounded(lambda: StdioTransport(self.cmd("refuses_start")))
        self.assertIn("licence refused", str(error))
        self.assertTrue(gone(self.pids()), "process left running")

    def test_a_call_that_gets_no_answer_times_out_and_the_server_is_stopped(self):
        for mode in ("silent_call", "ignores_sigterm", "grandchild"):
            with self.subTest(mode):
                t = self.started(mode)
                _, error = self.bounded(lambda: t.call("dwsim_solve_run", {}))
                self.assertIsInstance(error, TimeoutError, error)
                self.assertTrue(gone(self.pids()), "process (or its child) left running")
                _, again = self.bounded(lambda: t.call("dwsim_solve_run", {}))
                self.assertIn("build", str(again))                       # says what to do; does not touch the dead pipe
                _, error = self.bounded(t.close); self.assertIsNone(error)

    def test_a_server_that_stops_reading_cannot_block_the_write(self):
        def go():
            t = StdioTransport.__new__(StdioTransport)
            t.p = subprocess.Popen(self.cmd("never_reads"), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, start_new_session=True)
            t._id, t.timeout, t.broken = 0, 5.0, None
            t.call("dwsim_solve_run", {"blob": "x" * 5_000_000})
        _, error = self.bounded(go)
        self.assertIsInstance(error, TimeoutError, error)
        self.assertTrue(self.pids(), "the fake never started, so nothing was checked")
        self.assertTrue(gone(self.pids()))

    def test_close_ends_a_server_that_ignores_end_of_input_and_stop_signals(self):
        for mode in ("deaf_to_eof", "ignores_sigterm"):
            with self.subTest(mode):
                t = self.started(mode)
                with mock.patch.object(DT_backend(), "CLOSE_WAIT_S", 0.5, create=True):
                    _, error = self.bounded(t.close)
                self.assertIsNone(error); self.assertTrue(gone(self.pids()))
                _, error = self.bounded(t.close); self.assertIsNone(error)      # closing twice is harmless

    def test_a_healthy_server_still_works_and_exits_on_close(self):
        t = self.started("ok")
        t.timeout = float(START_S)
        self.assertEqual(self.bounded(lambda: t.call("dwsim_flowsheet_create", {}))[0], {"flowsheet_id": "fs-1"})
        self.bounded(t.close); self.assertTrue(gone(self.pids()))

    def test_a_bad_timeout_setting_is_refused_before_anything_starts(self):
        for bad in ("0", "-5", "soon", "nan", "inf"):
            with self.subTest(bad), mock.patch.dict(os.environ, {"DWSIM_MCP_TIMEOUT_S": bad}):
                _, error = self.bounded(lambda: StdioTransport(self.cmd("ok")))
                self.assertIsInstance(error, ValueError, error)
                self.assertIn("DWSIM_MCP_TIMEOUT_S", str(error))
        self.assertEqual(self.pids(), [])

    def test_the_tool_server_keeps_answering_after_dwsim_hangs(self):
        path = os.path.join(os.path.dirname(self.script), "s.json"); sheet().to_json(path)
        env = {**os.environ, "PYTHONPATH": ROOT, "PYTHONDONTWRITEBYTECODE": "1",
               "DWSIM_MCP_CMD": " ".join(self.cmd("silent_call")), "DWSIM_MCP_TIMEOUT_S": "5"}
        def msg(i, method, **params): return json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params}) + "\n"
        text = (msg(1, "tools/call", name="load_flowsheet_json", arguments={"name": "s", "path": path})
                + msg(2, "tools/call", name="dwsim_build", arguments={"name": "s", "confirm": True, "live": True})
                + msg(3, "tools/call", name="dwsim_solve", arguments={"name": "s"})
                + msg(4, "ping"))
        try:
            p = subprocess.run([sys.executable, "-m", "hysys_bridge.mcp_server"], input=text, capture_output=True, text=True, env=env, timeout=LIMIT)
        except subprocess.TimeoutExpired:
            self.fail("the tool server froze")
        replies = {r["id"]: r for r in map(json.loads, p.stdout.splitlines())}
        self.assertIn(4, replies)
        failed = [replies[i]["result"] for i in (2, 3) if replies[i]["result"]["isError"]]
        self.assertTrue(failed and "did not answer" in failed[0]["content"][0]["text"], replies)
        self.assertTrue(gone(self.pids()))


def DT_backend():
    from hysys_bridge.dwsim import backend
    return backend


class FakeAspen:
    """Stands in for pythoncom and win32com. Records which thread each COM step ran on."""
    def __init__(self, open_error=None, close_error=None):
        self.log, self.open_error, self.close_error = [], open_error, close_error
        outer = self

        class App:
            def InitFromFile2(self, path):
                outer.note("open")
                if outer.open_error: raise outer.open_error

            def Close(self):
                outer.note("Close")
                if outer.close_error: raise outer.close_error

        self.pythoncom = types.SimpleNamespace(CoInitialize=lambda: self.note("CoInitialize"), CoUninitialize=lambda: self.note("CoUninitialize"))
        client = types.SimpleNamespace(Dispatch=lambda name: App())
        self.modules = {"pythoncom": self.pythoncom, "win32com": types.SimpleNamespace(client=client), "win32com.client": client}

    def note(self, what): self.log.append((what, threading.get_ident()))

    def steps(self): return [w for w, _ in self.log]


class AspenCleanup(unittest.TestCase):
    def use(self, fake):
        for p in (mock.patch.dict(sys.modules, fake.modules), mock.patch.object(AB.sys, "platform", "win32")):
            p.start(); self.addCleanup(p.stop)
        return fake

    def test_close_closes_the_document_on_the_thread_that_owns_it(self):
        fake = self.use(FakeAspen())
        tree = AB.AspenComTree("model.apw"); tree.close()
        self.assertEqual(fake.steps(), ["CoInitialize", "open", "Close", "CoUninitialize"])
        self.assertEqual(len({t for _, t in fake.log}), 1)
        self.assertIsNone(tree.app)

    def test_closing_twice_is_harmless_and_a_closed_case_refuses_use(self):
        fake = self.use(FakeAspen())
        tree = AB.AspenComTree("model.apw"); tree.close(); tree.close()
        self.assertEqual(fake.steps().count("Close"), 1)
        with self.assertRaisesRegex(RuntimeError, "closed"): tree.reinit()

    def test_a_failed_close_is_reported_and_still_releases_the_thread(self):
        fake = self.use(FakeAspen(close_error=OSError("COM server busy")))
        tree = AB.AspenComTree("model.apw")
        with self.assertRaisesRegex(RuntimeError, "may still be running"): tree.close()
        self.assertIn("CoUninitialize", fake.steps()); self.assertIsNone(tree.app)

    def test_a_model_that_fails_to_open_does_not_leave_aspen_open(self):
        fake = self.use(FakeAspen(open_error=OSError("bad file")))
        with self.assertRaisesRegex(OSError, "bad file"): AB.AspenComTree("model.apw")
        self.assertEqual(fake.steps(), ["CoInitialize", "open", "Close", "CoUninitialize"])


class Recorder:
    def __init__(self, error=None): self.closed, self.error = 0, error
    def close(self):
        self.closed += 1
        if self.error: raise self.error


class ServerShutdown(unittest.TestCase):
    def test_open_cases_are_closed_when_the_tool_server_stops_even_if_one_fails(self):
        for store in (DT.CASES, AT.CASES):
            store.clear(); self.addCleanup(store.clear)
        bad, dwsim, aspen = Recorder(OSError("stuck")), Recorder(), Recorder()
        DT.CASES.update(a={"transport": bad}, b={"transport": dwsim}); AT.CASES["c"] = {"tree": aspen}
        with mock.patch.object(sys, "stdin", io.StringIO("")), mock.patch.object(sys, "stderr", io.StringIO()) as err:
            M.main()
        self.assertEqual((bad.closed, dwsim.closed, aspen.closed), (1, 1, 1))
        self.assertEqual((DT.CASES, AT.CASES), ({}, {}))
        self.assertIn("stuck", err.getvalue())


if __name__ == "__main__":
    unittest.main()
