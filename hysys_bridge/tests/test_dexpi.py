import os, unittest, xml.etree.ElementTree as ET
from hysys_bridge import dexpi_export, extract_hmb, normalize, pid_eval

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample", "hmb.csv")


def sample():
    fs = extract_hmb.from_csv(SAMPLE); normalize.normalize(fs); return fs


class D(unittest.TestCase):
    def test_wellformed_and_structure(self):
        xml = dexpi_export.export(sample())
        root = ET.fromstring(xml)
        self.assertEqual(root.tag, "PlantModel"); self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        self.assertEqual(len(root.findall("Equipment")), 2)
        segs = root.findall("PipingNetworkSystem/PipingNetworkSegment")
        self.assertEqual(len(segs), 4)
        ids = {e.get("ID") for e in root.iter() if e.get("ID")}
        for seg in segs:                                                   # every end resolves or is a boundary
            c = seg.find("Connection")
            for k in ("FromID", "ToID"):
                if c.get(k) is not None: self.assertIn(c.get(k), ids)
            n_open = sum(c.get(k) is None for k in ("FromID", "ToID"))
            self.assertLessEqual(n_open, 1)                                # a segment cannot be open at both ends here
        self.assertEqual(len({e.get("ID") for e in root.iter() if e.get("ID")}), len([e for e in root.iter() if e.get("ID")]))

    def test_round_trip_preserves_topology_and_data(self):
        a = sample(); b = dexpi_export.load(dexpi_export.export(a))
        s = pid_eval.score(b, a)
        self.assertEqual((s.node_f1, s.edge_f1, s.adjacency_acc, s.type_acc), (1.0, 1.0, 1.0, 1.0))
        self.assertAlmostEqual(b.streams["1"].P_kPa, a.streams["1"].P_kPa)
        self.assertAlmostEqual(b.streams["3"].composition["Ethanol"], 0.334)
        self.assertEqual(b.streams["1"].kind, "feed"); self.assertEqual(b.streams["4"].kind, "product")
        self.assertEqual(b.units["E-100"].type, "heater")

    def test_rejects_non_plantmodel(self):
        with self.assertRaises(ValueError): dexpi_export.load("<Foo/>")

    def test_dangling_reference_rejected(self):
        xml = dexpi_export.export(sample()).replace('ToID="EQ-E-100-N1"', 'ToID="NOPE"', 1)
        with self.assertRaises(ValueError): dexpi_export.load(xml)

    def test_file_written(self):
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "x.xml"); dexpi_export.export(sample(), p)
        with open(p, encoding="utf-8") as f: self.assertIn("PlantModel", f.read())

def rich():
    """pump -> heater -> separator, with the numbers DEXPI can hold."""
    from hysys_bridge.ir import Flowsheet, Stream, Unit
    f = Flowsheet(name="rich")
    f.units = {"P-1": Unit("P-1", "pump"), "E-1": Unit("E-1", "heater"), "V-1": Unit("V-1", "separator")}
    mk = lambda i, a, b, **kw: Stream(i, src=a, dst=b, **kw)
    f.streams = {
        "1": mk("1", None, "P-1", T_C=25.0, P_kPa=100.0, vol_flow_m3_h=12.0, composition={"Water": 0.9, "Ethanol": 0.1}, checks={"enthalpy_kJ_h": 1000.0}),
        "2": mk("2", "P-1", "E-1", T_C=25.5, P_kPa=600.0, composition={"Water": 0.9, "Ethanol": 0.1}, checks={"enthalpy_kJ_h": 1500.0}),
        "3": mk("3", "E-1", "V-1", T_C=80.0, P_kPa=550.0, vol_flow_m3_h=13.0, composition={"Water": 0.9, "Ethanol": 0.1}, checks={"enthalpy_kJ_h": 361500.0}),
        "4": mk("4", "V-1", None, T_C=80.0, P_kPa=500.0, composition={"Water": 0.9, "Ethanol": 0.1}),
    }
    f.relink(); return f


class Mapping(unittest.TestCase):
    def test_values_written_as_dexpi_attributes(self):
        root = ET.fromstring(dexpi_export.export(rich()))
        def dx(el):
            return {a.get("Name"): (a.get("Value"), a.get("Units")) for g in el.findall("GenericAttributes")
                    if g.get("Set") == "DexpiAttributes" for a in g.findall("GenericAttribute")}
        eq = {e.get("TagName"): dx(e) for e in root.findall("Equipment")}
        self.assertEqual(eq["P-1"]["DifferentialPressure"], ("500.0", "Kilopascal"))
        self.assertEqual(eq["P-1"]["DesignVolumeFlowRate"], ("12.0", "MetreCubedPerHour"))
        self.assertEqual(eq["E-1"]["DesignHeatFlowRate"], ("100.0", "Kilowatt"))          # (361500-1500)/3600
        self.assertEqual(eq["V-1"]["DesignVolumeFlowRate"], ("13.0", "MetreCubedPerHour"))
        seg = {s.get("TagName"): dx(s) for s in root.iter("PipingNetworkSegment")}
        self.assertEqual(seg["3"]["OperatingTemperature"], ("80.0", "DegreeCelsius"))
        self.assertEqual(seg["3"]["FluidCode"][0], "Water")

    def test_only_what_exists_is_written(self):
        f = rich(); f.streams["1"].vol_flow_m3_h = None; f.streams["3"].checks = {}
        root = ET.fromstring(dexpi_export.export(f))
        names = {a.get("Name") for e in root.findall("Equipment") for g in e.findall("GenericAttributes")
                 if g.get("Set") == "DexpiAttributes" for a in g.findall("GenericAttribute")}
        self.assertNotIn("DesignHeatFlowRate", names); self.assertIn("DifferentialPressure", names)

    def test_round_trip_keeps_params_and_dexpi_only_temperature(self):
        b = dexpi_export.load(dexpi_export.export(rich()))
        self.assertAlmostEqual(b.units["P-1"].params["DifferentialPressure_kPa"], 500.0)
        self.assertAlmostEqual(b.units["E-1"].params["DesignHeatFlowRate_kW"], 100.0)
        xml = dexpi_export.export(rich())                                     # strip custom sets: a standard-reader view
        root = ET.fromstring(xml)
        for seg in root.iter("PipingNetworkSegment"):
            for g in seg.findall("GenericAttributes"):
                if g.get("Set") == "StreamData": seg.remove(g)
        c = dexpi_export.load(ET.tostring(root, encoding="unicode"))
        self.assertEqual(c.streams["3"].T_C, 80.0); self.assertIsNone(c.streams["3"].P_kPa)


def piping():
    """feed -> pump -> valve -> splitter -> (separator V-1 | separator V-2 -> reactor -> unknown) """
    from hysys_bridge.ir import Flowsheet, Stream, Unit
    f = Flowsheet(name="piping")
    f.units = {u: Unit(u, t) for u, t in [("P-1", "pump"), ("FV-1", "valve"), ("SP-1", "splitter"), ("V-1", "separator"),
                                          ("V-2", "separator"), ("R-1", "reactor"), ("X-1", "unknown")]}
    edges = [("1", None, "P-1"), ("2", "P-1", "FV-1"), ("3", "FV-1", "SP-1"), ("4", "SP-1", "V-1"), ("5", "SP-1", "V-2"),
             ("6", "V-1", None), ("7", "V-2", "R-1"), ("8", "R-1", "X-1"), ("9", "X-1", None)]
    f.streams = {i: Stream(i, src=a, dst=b, T_C=10.0 + int(i), P_kPa=100.0 * int(i)) for i, a, b in edges}
    f.relink(); return f


class Classes(unittest.TestCase):
    def test_xml_encoding_of_reactor_unknown_valve_splitter(self):
        root = ET.fromstring(dexpi_export.export(piping()))
        eq = {e.get("TagName"): e.get("ComponentClass") for e in root.findall("Equipment")}
        self.assertEqual(eq["R-1"], "PressureVessel"); self.assertEqual(eq["X-1"], "ProcessEquipment")
        self.assertNotIn("FV-1", eq); self.assertNotIn("SP-1", eq)                 # not equipment
        segs = {s.get("TagName"): s for s in root.iter("PipingNetworkSegment")}
        self.assertEqual(sorted(segs), ["1", "2", "5", "6", "7", "8", "9"])         # 3 and 4 fold into run 2
        self.assertEqual([(c.get("TagName"), c.get("ComponentClass")) for c in segs["2"].findall("PipingComponent")],
                         [("FV-1", "OperatedValve"), ("SP-1", "PipeTee")])
        self.assertEqual(segs["5"].find("Connection").get("FromID"), "EQ-SP-1")     # branch leaves the tee

    def test_round_trip_restores_valve_splitter_and_folded_streams(self):
        a = piping(); b = dexpi_export.load(dexpi_export.export(a))
        s = pid_eval.score(b, a)
        self.assertEqual((s.node_f1, s.edge_f1, s.adjacency_acc, s.type_acc), (1.0, 1.0, 1.0, 1.0))
        self.assertEqual({u.id: u.type for u in b.units.values()}, {u.id: u.type for u in a.units.values()})
        for sid in ("3", "4"):                                                      # folded streams keep their own data
            self.assertAlmostEqual(b.streams[sid].P_kPa, a.streams[sid].P_kPa); self.assertAlmostEqual(b.streams[sid].T_C, a.streams[sid].T_C)

    def test_odd_valve_and_splitter_fall_back_to_equipment(self):
        f = piping(); f.units["FV-1"].type = "splitter"                              # splitter with 1 outlet: not a tee
        root = ET.fromstring(dexpi_export.export(f))
        self.assertEqual({e.get("TagName"): e.get("ComponentClass") for e in root.findall("Equipment")}["FV-1"], "ProcessEquipment")
        b = dexpi_export.load(dexpi_export.export(f))
        self.assertEqual(b.units["FV-1"].type, "splitter")

    def test_cycle_of_valves_rejected(self):
        from hysys_bridge.ir import Flowsheet, Stream, Unit
        f = Flowsheet(); f.units = {"A": Unit("A", "valve"), "B": Unit("B", "valve")}
        f.streams = {"1": Stream("1", src="A", dst="B"), "2": Stream("2", src="B", dst="A")}; f.relink()
        with self.assertRaises(ValueError): dexpi_export.export(f)


try:
    from pydexpi.loaders.proteus_serializer import ProteusSerializer
except ImportError:
    ProteusSerializer = None


@unittest.skipUnless(ProteusSerializer, "pydexpi not installed")
class PyDexpiLoad(unittest.TestCase):
    def test_sample_loads_and_connections_resolve(self):
        import tempfile, pathlib
        d = tempfile.mkdtemp(); dexpi_export.export(sample(), os.path.join(d, "x.xml"))
        ser = ProteusSerializer(); cm = ser.load(pathlib.Path(d), "x.xml").conceptualModel
        errs = [e.message[:120] for e in ser.get_loading_errors().errors if e.level.value == "error"]
        self.assertEqual(errs, [])                                         # warnings (custom attribute sets) are expected
        self.assertEqual(sorted(type(e).__name__ for e in cm.taggedPlantItems), ["HeatExchanger", "Mixer"])
        segs = cm.pipingNetworkSystems[0].segments
        self.assertEqual(sorted(e.tagName for e in cm.taggedPlantItems), ["E-100", "MX-100"])
        feed = next(s for s in segs if s.id == "SEG-1")
        self.assertIsNone(feed.sourceItem); self.assertEqual(feed.targetItem.id, "EQ-MX-100-N1")
        prod = next(s for s in segs if s.id == "SEG-4")
        self.assertEqual(prod.sourceItem.id, "EQ-E-100-N2"); self.assertIsNone(prod.targetItem)
        mid = next(s for s in segs if s.id == "SEG-3").connections[0]
        self.assertEqual((mid.sourceItem.id, mid.targetItem.id), ("EQ-MX-100-N3", "EQ-E-100-N1"))


@unittest.skipUnless(ProteusSerializer, "pydexpi not installed")
class PyDexpiMapping(unittest.TestCase):
    def test_pydexpi_reads_the_mapped_attributes(self):
        import tempfile, pathlib
        d = tempfile.mkdtemp(); dexpi_export.export(rich(), os.path.join(d, "r.xml"))
        ser = ProteusSerializer(); cm = ser.load(pathlib.Path(d), "r.xml").conceptualModel
        self.assertEqual([e.message[:100] for e in ser.get_loading_errors().errors if e.level.value == "error"], [])
        # pyDEXPI logs INFO when a unit literal is shared by gauge/absolute leaves (differentialPressure -> absolute
        # leaf per DEXPI 2.0.1; a pressure difference is the same either way). Anything above INFO about units fails.
        bad_unit = [e.message[:100] for e in ser.get_loading_errors().errors
                    if "unit" in e.message.lower() and e.level.value != "info"]
        self.assertEqual(bad_unit, [])
        eq = {e.tagName: e for e in cm.taggedPlantItems}
        self.assertEqual((eq["P-1"].differentialPressure.value, eq["P-1"].differentialPressure.unit.value), (500.0, "Kilopascal"))
        self.assertEqual(eq["P-1"].designVolumeFlowRate.value, 12.0)
        self.assertEqual((eq["E-1"].designHeatFlowRate.value, eq["E-1"].designHeatFlowRate.unit.value), (100.0, "Kilowatt"))
        self.assertEqual(eq["V-1"].designVolumeFlowRate.value, 13.0)
        seg = {s.id: s for s in cm.pipingNetworkSystems[0].segments}
        self.assertEqual((seg["SEG-3"].operatingTemperature.value, seg["SEG-3"].operatingTemperature.unit.value), (80.0, "DegreeCelsius"))
        self.assertEqual(seg["SEG-3"].fluidCode, "Water")


@unittest.skipUnless(ProteusSerializer, "pydexpi not installed")
class PyDexpiClasses(unittest.TestCase):
    def test_pydexpi_recognises_the_mapped_classes(self):
        import tempfile, pathlib
        d = tempfile.mkdtemp(); dexpi_export.export(piping(), os.path.join(d, "p.xml"))
        ser = ProteusSerializer(); cm = ser.load(pathlib.Path(d), "p.xml").conceptualModel
        errs = [e.message[:140] for e in ser.get_loading_errors().errors if e.level.value == "error"]
        self.assertEqual(errs, [])
        names = {e.tagName: type(e).__name__ for e in cm.taggedPlantItems}
        self.assertEqual((names["R-1"], names["X-1"], names["P-1"], names["V-1"]), ("PressureVessel", "ProcessEquipment", "CentrifugalPump", "Separator"))
        segs = {s.id: s for s in cm.pipingNetworkSystems[0].segments}
        self.assertEqual([type(i).__name__ for i in segs["SEG-2"].items], ["OperatedValve", "PipeTee"])
        self.assertEqual(segs["SEG-5"].sourceItem.id, "EQ-SP-1")                    # branch starts at the tee
        self.assertEqual((segs["SEG-2"].sourceItem.id if segs["SEG-2"].sourceItem else None), "EQ-P-1-N2")


if __name__ == "__main__": unittest.main()
