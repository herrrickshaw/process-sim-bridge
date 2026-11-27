import copy, csv, os, tempfile, unittest

from hysys_bridge import dexpi_export, extract_hmb, hmb_report_link as L, mcp_server

TOOLKIT = os.environ.get("PROCESS_SAFETY_PATH")
HAVE = bool(TOOLKIT) and os.path.isfile(os.path.join(TOOLKIT, "process_safety", "hmb_audit.py"))
SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample", "hmb.csv")


class Convert(unittest.TestCase):
    """No toolkit needed: the conversion must not fill gaps."""
    def test_sample_converts_without_inventing_values(self):
        s = {x["id"]: x for x in L.to_spec(extract_hmb.from_csv(SAMPLE))["streams"]}
        self.assertAlmostEqual(s["1"]["P_kpag"], 200.0)
        self.assertIsNone(s["1"]["H_kW"])
        self.assertIsNone(s["1"]["from"])
        self.assertEqual(s["1"]["component_basis"], "mole")

    def test_bad_extra_is_refused(self):
        fs = extract_hmb.from_csv(SAMPLE)
        for extra in ({"duty": 1}, {"unit_data": {"X-1": {}}}, {"unit_data": {"E-100": {"duty": 5}}}, {"line_map": {"99": "L"}}):
            with self.assertRaises(ValueError):
                L.to_spec(fs, extra=extra)

    def test_mcp_lists_the_tool(self):
        self.assertIn("safety_hmb_report", mcp_server.TOOLS)


@unittest.skipUnless(HAVE, "set PROCESS_SAFETY_PATH to a toolkit checkout that has process_safety/hmb_audit.py")
class WithToolkit(unittest.TestCase):
    def test_sample_is_incomplete_not_passed(self):
        with tempfile.TemporaryDirectory() as t:
            r = L.build(extract_hmb.from_csv(SAMPLE), None, None, None, t)
            self.assertEqual(r["verdict"], "not_checked", r["findings"])
            self.assertEqual(r["counts"]["fail"], 0)
            self.assertTrue(all(os.path.getsize(f) for f in r["files"]))
            with self.assertRaises(FileExistsError):
                L.build(extract_hmb.from_csv(SAMPLE), None, None, None, t)

    def test_dexpi_pid_links_and_catches_a_reversed_stream(self):
        fs = extract_hmb.from_csv(SAMPLE)
        with tempfile.TemporaryDirectory() as t:
            x = os.path.join(t, "p.xml"); dexpi_export.export(fs, x)
            pid = dexpi_export.load(x)
            ok = L.build(fs, fs, pid, None, os.path.join(t, "a"))
            self.assertFalse([f for f in ok["findings"] if f["area"] == "P&ID link" and f["status"] == "fail"], ok["findings"])
            wrong = copy.deepcopy(fs); s = wrong.streams["3"]; s.src, s.dst = s.dst, s.src
            bad = L.build(wrong, None, pid, None, os.path.join(t, "b"))
            self.assertIn(("fail", "P&ID link", "3"), {(f["status"], f["area"], f["item"]) for f in bad["findings"]})


if __name__ == "__main__":
    unittest.main()
