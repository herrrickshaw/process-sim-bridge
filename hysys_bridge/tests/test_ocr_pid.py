import json, unittest
from hysys_bridge import ocr, pid_extract, extract_hmb


def W(text, x, top, conf=99.0): return (text, x, x + 30, top, conf)


class OCR(unittest.TestCase):
    def grid(self, bad=None):
        w = []
        data = [("Stream No.", ["1", "2"]), ("From", ["-", "A-1"]), ("To", ["A-1", "-"]),
                ("Pressure (barg)", ["2.0", "1.5"]), ("Mass flow (kg/h)", ["1000", "1000"])]
        for r, (lab, vals) in enumerate(data):
            top = 10 + r * 30
            for k, t in enumerate(lab.split()): w.append(W(t, 5 + k * 40, top))
            for c, v in enumerate(vals): w.append(W(v, 300 + c * 100, top, 60.0 if bad == (r, c) else 99.0))
        return w

    def test_rows_rebuilt_and_parse(self):
        rows, review = ocr.words_to_rows(self.grid())
        self.assertEqual(rows[3], ["Pressure (barg)", "2.0", "1.5"]); self.assertEqual(review, [])
        fs = extract_hmb.from_rows(rows)
        self.assertAlmostEqual(fs.streams["2"].P_kPa, 150 + 101.325)

    def test_low_confidence_cell_goes_to_review(self):
        _, review = ocr.words_to_rows(self.grid(bad=(4, 1)))
        self.assertEqual(review, [(4, 2, "1000", 60.0)])


class PID(unittest.TestCase):
    def ask_factory(self, streams):
        units = {"units": [{"id": "P-1", "type": "pump", "label": ""}, {"id": "E-1", "type": "heater", "label": ""}]}
        return lambda prompt: "```json\n" + json.dumps(units if "unit operation" in prompt else {"streams": streams}) + "\n```"

    def test_two_pass_topology_and_flags(self):
        fs = pid_extract.parse_two_pass(self.ask_factory([
            {"id": "1", "src": None, "dst": "P-1"}, {"id": "2", "src": "P-1", "dst": "E-1"},
            {"id": "3", "src": "E-1", "dst": None}]))
        self.assertEqual([s.kind for s in fs.streams.values()], ["feed", "intermediate", "product"])
        self.assertTrue(all("needs-signoff" in u.flags for u in fs.units.values()))
        self.assertEqual(fs.units["P-1"].inlets, ["1"])

    def test_hallucinated_unit_rejected(self):
        with self.assertRaises(ValueError):
            pid_extract.parse_two_pass(self.ask_factory([{"id": "1", "src": None, "dst": "X-9"}]))

    def test_merge_reports_topology_conflict(self):
        topo = pid_extract.parse_two_pass(self.ask_factory([
            {"id": "1", "src": None, "dst": "P-1"}, {"id": "2", "src": "P-1", "dst": "E-1"}]))
        hmb = extract_hmb.from_rows([["Stream No.", "1", "2", "9"], ["From", "-", "P-1", "-"], ["To", "P-1", "E-2", "-"],
                                    ["Temperature (°C)", "25", "26", "27"]])
        notes = pid_extract.merge_values(topo, hmb)
        self.assertTrue(any("stream 2" in n and "E-2" in n for n in notes))
        self.assertTrue(any("stream 9" in n for n in notes))
        self.assertEqual(topo.streams["1"].T_C, 25)


if __name__ == "__main__":
    unittest.main()
