import os, tempfile, unittest
from hysys_bridge import extract_hmb, normalize
from hysys_bridge.ir import Flowsheet, Stream, Unit

try:
    from hysys_bridge import dexpi_process
    import pydexpi  # noqa: F401
    HAVE = True
except SystemExit:
    HAVE = False
except ImportError:
    HAVE = False

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample", "hmb.csv")


def sample():
    fs = extract_hmb.from_csv(SAMPLE); normalize.normalize(fs); return fs


@unittest.skipUnless(HAVE, "pydexpi not installed")
class ProcessModel(unittest.TestCase):
    def roundtrip(self, fs):
        d = tempfile.mkdtemp(); dexpi_process.export_json(fs, d, "p.json")
        return dexpi_process.read_streams(d, "p.json")

    def test_values_topology_and_boundaries_survive(self):
        fs = sample(); back = self.roundtrip(fs)
        self.assertEqual(set(back), set(fs.streams))
        for sid, s in fs.streams.items():
            b = back[sid]
            self.assertEqual((b["src"], b["dst"]), (s.src, s.dst))
            self.assertAlmostEqual(b["T_C"], s.T_C); self.assertAlmostEqual(b["P_kPa"], s.P_kPa)
            self.assertAlmostEqual(b["mass_flow_kg_h"], s.mass_flow_kg_h)
            for c, x in s.composition.items(): self.assertAlmostEqual(b["composition"].get(c, 0.0), x)
            self.assertEqual(b["basis"], "mole")
        self.assertIsNone(back["1"]["src"]); self.assertIsNone(back["4"]["dst"])

    def test_mass_basis_and_enthalpy_and_volume_flow(self):
        fs = Flowsheet(name="m"); fs.components = ["A", "B"]
        fs.units = {"P-1": Unit("P-1", "pump")}
        fs.streams = {
            "1": Stream("1", dst="P-1", T_C=20.0, P_kPa=100.0, vol_flow_m3_h=5.0, mass_flow_kg_h=4000.0, composition={"A": 0.25, "B": 0.75},
                        composition_basis="mass", checks={"enthalpy_kJ_h": 8000.0}),
            "2": Stream("2", src="P-1", P_kPa=500.0)}
        fs.relink(); b = self.roundtrip(fs)
        self.assertEqual(b["1"]["basis"], "mass"); self.assertAlmostEqual(b["1"]["composition"]["B"], 0.75)
        self.assertAlmostEqual(b["1"]["vol_flow_m3_h"], 5.0); self.assertAlmostEqual(b["1"]["specific_enthalpy_kJ_kg"], 2.0)
        self.assertIsNone(b["2"]["T_C"]); self.assertEqual(b["2"]["composition"], {})

    def test_units_are_dexpi_units(self):
        em = dexpi_process.build(sample())
        st = next(s for s in em.conceptualModel.processConnections if s.identifier == "3")
        self.assertEqual(st.temperature[0].value.unit.value, "DegreeCelsius")
        self.assertEqual(st.pressure[0].value.unit.value, "Kilopascal")
        self.assertEqual(st.massFlow[0].value.unit.value, "KilogramPerHour")

    def test_ports_link_back_to_their_stream(self):
        em = dexpi_process.build(sample())
        for st in em.conceptualModel.processConnections:
            self.assertIs(st.source.connectorReference, st); self.assertIs(st.target.connectorReference, st)


if __name__ == "__main__":
    unittest.main()
