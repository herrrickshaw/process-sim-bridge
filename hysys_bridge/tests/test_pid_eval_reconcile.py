import unittest
from hysys_bridge.ir import Flowsheet, Stream, Unit
from hysys_bridge import pid_eval, pid_reconcile


def fs(units, streams):
    f = Flowsheet(); f.units = {u: Unit(u, t) for u, t in units}
    f.streams = {i: Stream(i, src=a, dst=b) for i, a, b in streams}; f.relink(); return f


TRUTH = lambda: fs([("P-1", "pump"), ("E-1", "heater"), ("V-1", "separator")],
                   [("1", None, "P-1"), ("2", "P-1", "E-1"), ("3", "E-1", "V-1"), ("4", "V-1", None), ("5", "V-1", None)])


class Eval(unittest.TestCase):
    def test_perfect(self):
        s = pid_eval.score(TRUTH(), TRUTH())
        self.assertEqual((s.node_f1, s.edge_f1, s.adjacency_acc, s.type_acc), (1.0, 1.0, 1.0, 1.0))

    def test_missing_edge_and_hallucinated_unit(self):
        p = fs([("P-1", "pump"), ("E-1", "heater"), ("V-1", "separator"), ("X-9", "valve")],
               [("1", None, "P-1"), ("2", "P-1", "E-1"), ("4", "V-1", None), ("5", "V-1", None), ("6", "E-1", "X-9")])
        s = pid_eval.score(p, TRUTH())
        self.assertAlmostEqual(s.node_p, 0.75); self.assertEqual(s.node_r, 1.0)
        self.assertAlmostEqual(s.edge_p, 0.8); self.assertAlmostEqual(s.edge_r, 0.8)   # 4 of 5 each: missed E-1->V-1, invented E-1->X-9
        self.assertLess(s.adjacency_acc, 1.0)

    def test_direction_flip_counted(self):
        p = TRUTH(); p.streams["2"].src, p.streams["2"].dst = "E-1", "P-1"; p.relink()
        s = pid_eval.score(p, TRUTH())
        self.assertEqual(s.direction_flips, 1); self.assertEqual(s.undirected_f1, 1.0); self.assertLess(s.edge_f1, 1.0)

    def test_structure_matching_ignores_ids(self):
        t = TRUTH()
        p = fs([("A", "pump"), ("B", "heater"), ("C", "separator")],
               [("1", None, "A"), ("2", "A", "B"), ("3", "B", "C"), ("4", "C", None), ("5", "C", None)])
        self.assertLess(pid_eval.score(p, t, "id").edge_f1, 1.0)      # ids differ: id matching cannot pair them
        s = pid_eval.score(p, t, "structure")
        self.assertEqual(s.edge_f1, 1.0); self.assertEqual(s.type_acc, 1.0)

    def test_hungarian_small(self):
        pairs = dict(pid_eval.hungarian([[4, 1, 3], [2, 0, 5], [3, 2, 2]]))
        self.assertEqual(sum([[4, 1, 3], [2, 0, 5], [3, 2, 2]][i][j] for i, j in pairs.items()), 5)


class Reconcile(unittest.TestCase):
    def test_clean_flowsheet_has_no_errors(self):
        iss, acts = pid_reconcile.reconcile(TRUTH())
        self.assertEqual([i for i in iss if i.level == "error"], []); self.assertEqual(acts, [])

    def test_autofix_self_loop_and_isolated(self):
        f = TRUTH(); f.streams["9"] = Stream("9", src="E-1", dst="E-1"); f.units["Z-1"] = Unit("Z-1", "valve"); f.relink()
        iss, acts = pid_reconcile.reconcile(f, fix=True)
        self.assertEqual(len(acts), 2); self.assertNotIn("9", f.streams); self.assertNotIn("Z-1", f.units)

    def test_ocr_confusable_tags_error(self):
        f = fs([("P-101", "pump"), ("P-1O1", "pump")], [("1", None, "P-101"), ("2", "P-101", "P-1O1"), ("3", "P-1O1", None)])
        iss, _ = pid_reconcile.reconcile(f)
        self.assertTrue(any(i.level == "error" and "OCR" in i.msg for i in iss))

    def test_degree_and_recycle(self):
        f = fs([("MX-1", "mixer"), ("P-1", "pump"), ("SP-1", "splitter")],
               [("1", None, "MX-1"), ("2", "MX-1", "P-1"), ("3", "P-1", "SP-1"), ("4", "SP-1", "MX-1"), ("5", "SP-1", None)])
        msgs = [i.msg for i in pid_reconcile.reconcile(f)[0]]
        self.assertTrue(any("recycle loop" in m for m in msgs))
        self.assertFalse(any("mixer with" in m for m in msgs))        # feed + recycle = 2 inlets: fine
        g = fs([("MX-1", "mixer")], [("1", None, "MX-1"), ("2", "MX-1", None)])
        self.assertTrue(any("mixer with 1 inlet" in i.msg for i in pid_reconcile.reconcile(g)[0]))

    def test_tag_shape_outlier(self):
        f = fs([("P-101", "pump"), ("P-102", "pump"), ("P-103", "pump"), ("PUMP", "pump")],
               [(str(i), None if i == 0 else "P-101", None) for i in range(1)] + [("a", "P-101", "P-102"), ("b", "P-102", "P-103"), ("c", "P-103", "PUMP"), ("d", "PUMP", None), ("e", None, "P-101")])
        self.assertTrue(any("PUMP" == i.where and "shape" in i.msg for i in pid_reconcile.reconcile(f)[0]))

    def test_disconnected(self):
        f = fs([("P-1", "pump"), ("P-2", "pump")], [("1", None, "P-1"), ("2", "P-1", None), ("3", None, "P-2"), ("4", "P-2", None)])
        self.assertTrue(any("disconnected" in i.msg for i in pid_reconcile.reconcile(f)[0]))


if __name__ == "__main__":
    unittest.main()
