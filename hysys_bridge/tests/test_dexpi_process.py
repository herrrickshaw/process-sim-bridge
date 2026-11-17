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

    def test_step_classes_are_typed_so_readers_can_categorise(self):
        from hysys_bridge.tests.test_dexpi import piping
        fs = piping(); fs.units["X-1"].type = "compressor"
        names = {st.identifier: type(st).__name__ for st in dexpi_process.build(fs).conceptualModel.processSteps}
        self.assertEqual({k: names[k] for k in ("P-1", "FV-1", "SP-1", "V-1", "R-1", "X-1")},
                         {"P-1": "Pumping", "FV-1": "RegulatingFlow", "SP-1": "SplittingMaterial", "V-1": "SeparatingByPhaseSeparation",
                          "R-1": "ReactingChemicals", "X-1": "Compressing"})

    def test_boundaries_are_source_and_sink_steps(self):
        names = {st.identifier: type(st).__name__ for st in dexpi_process.build(sample()).conceptualModel.processSteps}
        self.assertEqual(names["BOUNDARY-1"], "Source"); self.assertEqual(names["BOUNDARY-4"], "Sink")

    def test_composition_is_one_vector_and_overall_state_is_set(self):
        st = next(s for s in dexpi_process.build(sample()).conceptualModel.processConnections if s.identifier == "3")
        ms = st.materialStateReference
        self.assertIs(ms.state, ms.phases[0])                              # readers take the overall state from .state
        qv = ms.state.composition.moleFractions
        self.assertEqual(len(qv), 1); self.assertEqual(len(qv[0].value.values), 2)
        self.assertAlmostEqual(sum(qv[0].value.values), 1.0)
        self.assertEqual(qv[0].value.unit.value, "Fraction")

    def test_classes_with_a_mandatory_method_still_build(self):
        fs = Flowsheet(name="m"); fs.units = {"K-1": Unit("K-1", "compressor"), "C-1": Unit("C-1", "cooler"), "R-1": Unit("R-1", "reactor")}
        fs.streams = {"1": Stream("1", dst="K-1"), "2": Stream("2", src="K-1", dst="C-1"), "3": Stream("3", src="C-1", dst="R-1"), "4": Stream("4", src="R-1")}
        fs.relink()
        names = {st.identifier: type(st).__name__ for st in dexpi_process.build(fs).conceptualModel.processSteps}
        self.assertEqual((names["K-1"], names["C-1"], names["R-1"]), ("Compressing", "RemovingThermalEnergy", "ReactingChemicals"))


if __name__ == "__main__":
    unittest.main()
