import unittest
from hysys_bridge.ir import Flowsheet, Stream, Unit
from hysys_bridge import hysys_writer
from hysys_bridge.dwsim.backend import DwsimBackend, TOOLS
from hysys_bridge.dwsim.fake import FakeDwsim
from hysys_bridge.dwsim.guardrails import check_specs


def sheet(basis="mass"):
    fs = Flowsheet("t", "Peng-Robinson", ["Water"])
    fs.streams = {
        "F1": Stream("F1", "feed", None, "P1", T_C=25.0, P_kPa=101.325, mass_flow_kg_h=1000.0, composition={"Water": 1.0}, composition_basis=basis),
        "S2": Stream("S2", "intermediate", "P1", "H1", P_kPa=500.0),
        "S3": Stream("S3", "product", "H1", None, T_C=80.0, P_kPa=480.0)}
    fs.units = {"P1": Unit("P1", "pump"), "H1": Unit("H1", "heater")}
    fs.relink(); return fs


class Dwsim(unittest.TestCase):
    def build(self, **kw):
        fake = FakeDwsim(); be = DwsimBackend(fake, **kw)
        rows = hysys_writer.write(sheet(), be)
        return fake, be, rows

    def test_tool_names_are_the_real_underscore_names(self):
        self.assertTrue(all(v.startswith("dwsim_") and "." not in v for v in TOOLS.values()))

    def test_write_buffers_then_flushes_in_si(self):
        fake, be, rows = self.build()
        self.assertTrue(rows and all(r.status == "OK" for r in rows))
        self.assertEqual([c[0] for c in fake.calls],
                         ["dwsim_flowsheet_create", "dwsim_thermo_add_compounds", "dwsim_thermo_set_property_package"])
        self.assertTrue(be.solve())
        f1 = fake.objects["F1"]
        self.assertAlmostEqual(f1["temperature_K"], 298.15); self.assertAlmostEqual(f1["pressure_Pa"], 101325.0)
        self.assertAlmostEqual(f1["mass_flow_kg_s"], 1000 / 3600); self.assertEqual(f1["composition"], {"Water": 1.0})
        self.assertEqual(fake.package, "Peng-Robinson (PR)")

    def test_unit_specs_go_through_unitop_set_and_derived_streams_are_bare(self):
        fake, be, _ = self.build(); be.solve()
        self.assertEqual(set(fake.objects["S3"]) - {"kind", "flowsheet_id", "name"}, set())
        self.assertAlmostEqual(fake.params["P1"]["DeltaP"], 398675.0)                      # increase 101.325 -> 500 kPa
        self.assertEqual(fake.params["H1"]["CalcMode"], "OutletTemperature")
        self.assertAlmostEqual(fake.params["H1"]["OutletTemperature"], 353.15); self.assertAlmostEqual(fake.params["H1"]["DeltaP"], 20000.0)
        self.assertEqual(fake.ports["H1"], {"S2": ("feed_stream", 0), "S3": ("product_stream", 0)})
        self.assertAlmostEqual(be.read_stream("S3")["T"], 80.0)

    def test_solve_is_blocked_while_specs_are_open(self):
        fake = FakeDwsim(); be = DwsimBackend(fake)
        fs = sheet(); fs.streams["S3"].T_C = None
        hysys_writer.write(fs, be)
        self.assertFalse(be.solve()); self.assertFalse(fake.solved)
        self.assertIn("H1", be.last_solve["open"][0])

    def test_mole_basis_needs_molar_masses(self):
        fs = sheet("mole")
        with self.assertRaises(ValueError): hysys_writer.write(fs, DwsimBackend(FakeDwsim()))
        be = DwsimBackend(FakeDwsim(), mw={"Water": 18.015}); hysys_writer.write(fs, be)
        self.assertAlmostEqual(sum(be.get_comp("F1").values()), 1.0)

    def test_unknown_compound_and_package_fail_loudly(self):
        fs = sheet(); fs.components = ["Unobtainium"]
        with self.assertRaises(RuntimeError): hysys_writer.write(fs, DwsimBackend(FakeDwsim()))
        be = DwsimBackend(FakeDwsim());
        with self.assertRaises(RuntimeError): be.new_case("t", "Not A Package", ["Water"])

    def test_unmapped_unit_type_and_volume_flow_rejected(self):
        be = DwsimBackend(FakeDwsim()); be.new_case("t", "Peng-Robinson", ["Water"])
        with self.assertRaises(KeyError): be.add_unit("X", "column")
        be.add_stream("S")
        with self.assertRaises(KeyError): be.set("S", "vol", 1.0)

    def test_guardrail_reports_missing_inputs(self):
        self.assertEqual(check_specs(sheet()), [])
        fs = sheet(); fs.streams["S3"].T_C = None; fs.streams["F1"].mass_flow_kg_h = None
        miss = check_specs(fs)
        self.assertIn("feed F1: flow rate", miss); self.assertIn("heater H1: outlet S3 T_C", miss)


if __name__ == "__main__":
    unittest.main()
