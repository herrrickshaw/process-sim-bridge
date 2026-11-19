import sys, unittest
from hysys_bridge import hysys_writer
from hysys_bridge.aspen import catalogue as C
from hysys_bridge.aspen.backend import AspenBackend, MockTree, AspenComTree
from hysys_bridge.ir import Flowsheet, Stream, Unit
from hysys_bridge.dwsim.tests.test_dwsim import sheet

B = r"\Data\Blocks\{}\Input\{}"


def build(tree=None, fs=None, **kw):
    tree = tree or MockTree(); be = AspenBackend(tree, **kw)
    rows = hysys_writer.write(fs or sheet(), be)
    return tree, be, rows


class Aspen(unittest.TestCase):
    def test_write_roundtrip_reads_back_from_the_tree(self):
        tree, be, rows = build()
        self.assertTrue(rows and all(r.status == "OK" for r in rows), [r for r in rows if r.status != "OK"])
        self.assertAlmostEqual(tree.v[r"\Data\Streams\F1\Input\TEMP\MIXED"], 25.0)
        self.assertAlmostEqual(tree.v[r"\Data\Streams\F1\Input\PRES\MIXED"], 1.01325)          # kPa -> bar
        self.assertAlmostEqual(tree.v[r"\Data\Streams\F1\Input\TOTAL"], 1000.0)
        self.assertEqual(tree.attr[(r"\Data\Streams\F1\Input\FLOW\MIXED", 13)], "MASS-FRAC")
        self.assertEqual(tree.v[r"\Data\Streams\F1\Input\FLOW\MIXED\WATER"], 1.0)

    def test_blocks_ports_and_property_method(self):
        tree, be, _ = build()
        self.assertEqual(tree.children[C.BLOCKS_ROOT], ["P1!PUMP", "H1!HEATER"])
        self.assertIn("F1", tree.children[r"\Data\Blocks\P1\Ports\F"]); self.assertIn("S3", tree.children[r"\Data\Blocks\H1\Ports\P"])
        self.assertEqual(tree.v[C.PROPERTY_METHOD[0]], "PENG-ROB"); self.assertEqual(tree.children[C.COMPONENTS], ["WATER"])

    def test_unit_conversion_follows_the_nodes_unit_string(self):
        tree, be, rows = build(MockTree(units={"TEMP": "K", "PRES": "kPa"}))
        self.assertTrue(all(r.status == "OK" for r in rows))
        self.assertAlmostEqual(tree.v[r"\Data\Streams\F1\Input\TEMP\MIXED"], 298.15)
        self.assertAlmostEqual(tree.v[r"\Data\Streams\F1\Input\PRES\MIXED"], 101.325)

    def test_unknown_unit_string_is_refused_not_guessed(self):
        with self.assertRaises(ValueError): build(MockTree(units={"PRES": "torr"}))

    def test_mass_spec_on_a_mole_flow_node_is_refused(self):
        with self.assertRaises(ValueError): build(MockTree(units={"TOTAL": "kmol/hr"}))

    def test_outlet_specs_land_on_block_inputs_at_solve(self):
        tree, be, _ = build()
        self.assertNotIn(B.format("P1", "PRES"), tree.v)                                      # nothing on blocks before solve
        self.assertTrue(be.solve())
        self.assertEqual(tree.v[B.format("P1", "OPT_SPEC")], "PRES"); self.assertAlmostEqual(tree.v[B.format("P1", "PRES")], 5.0)
        self.assertAlmostEqual(tree.v[B.format("H1", "TEMP")], 80.0); self.assertAlmostEqual(tree.v[B.format("H1", "PRES")], 4.8)

    def test_incomplete_input_is_reported_by_node_path(self):
        fs = sheet(); fs.streams["S3"].P_kPa = None
        tree, be, _ = build(fs=fs)
        self.assertFalse(be.solve())
        self.assertEqual(be.last_run["missing_inputs"], [B.format("H1", "PRES")])

    def test_unverified_units_refused_unless_allowed(self):
        fs = sheet(); fs.units["P1"].type = "valve"
        with self.assertRaises(NotImplementedError): build(fs=fs)
        build(fs=fs, allow_unverified=True)

    def test_results_only_t_and_p_and_converted_back(self):
        tree = MockTree(results={r"\Data\Streams\S3\Output\RES_TEMP": 80.0, r"\Data\Streams\S3\Output\RES_PRES": 4.8})
        _, be, _ = build(tree); self.assertTrue(be.solve())
        self.assertAlmostEqual(be.read_result("S3", "T"), 80.0); self.assertAlmostEqual(be.read_result("S3", "P"), 480.0)
        with self.assertRaises(NotImplementedError): be.read_result("S3", "mass")

    def test_mole_basis_sets_the_basis_attribute(self):
        fs = sheet(); fs.streams["F1"].composition_basis = "mole"
        tree, _, _ = build(fs=fs)
        self.assertEqual(tree.attr[(r"\Data\Streams\F1\Input\FLOW\MIXED", 13)], "MOLE-FRAC")

    def test_catalogue_marks_what_is_unverified(self):
        self.assertEqual(sorted(k for k, v in C.BLOCK_MODEL.items() if v[1] == "guess"), ["compressor", "pump", "valve"])

    @unittest.skipIf(sys.platform == "win32", "non-Windows only")
    def test_com_tree_refuses_off_windows(self):
        with self.assertRaises(RuntimeError): AspenComTree()


if __name__ == "__main__":
    unittest.main()
