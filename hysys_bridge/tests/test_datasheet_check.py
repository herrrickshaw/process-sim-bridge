import json, os, tempfile, unittest
from unittest import mock
from hysys_bridge import datasheet_check as D, mcp_server as M
from hysys_bridge.ir import Flowsheet, Stream, Unit


def fs(T=80.0, P=300.0, mass=1000.0, utype="heater", params=None):
    f = Flowsheet("x", "Peng-Robinson", ["Water"])
    f.units = {"E-100": Unit("E-100", utype, params=dict(params or {}))}
    f.streams = {"S1": Stream("S1", "feed", None, "E-100", T_C=T, P_kPa=P, mass_flow_kg_h=mass)}
    return f


def sheet(*rows, name="vendor"):
    return D.rows_from_datasheet(name, "item,attribute,value,unit\n" + "\n".join(rows))


def codes(out): return [f["code"] for f in out["findings"]]
def of(out, code): return [f for f in out["findings"] if f["code"] == code]


class Compare(unittest.TestCase):
    def test_agreeing_sources_have_no_findings_after_unit_conversion(self):
        rows = D.rows_from_flowsheet("pid", fs()) + sheet("S1,T,353.15,K", "S1,P,2.0,barg", "S1,mass_flow,1.0,t/h", "E-100,type,Heater,")        # 80 C, 301.325 kPa abs is NOT 300: see next test
        out = D.check(rows, rel_tol=0.01); self.assertEqual(of(out, "VALUE_MISMATCH"), []); self.assertEqual(of(out, "TYPE_MISMATCH"), [])
        self.assertTrue(out["agree"])

    def test_value_mismatch_reports_size_and_both_values(self):
        out = D.check(D.rows_from_flowsheet("pid", fs(P=300.0)) + sheet("S1,P,2.0,barg"), rel_tol=0.001)
        f = of(out, "VALUE_MISMATCH"); self.assertEqual(len(f), 1); self.assertEqual((f[0]["item"], f[0]["attribute"]), ("S1", "P")); self.assertIn("1.325", f[0]["detail"])
        self.assertEqual({v["source"] for v in f[0]["values"]}, {"pid", "vendor"}); self.assertFalse(out["agree"])

    def test_temperature_difference_is_given_in_degrees_not_percent(self):
        f = of(D.check(D.rows_from_flowsheet("pid", fs(T=80)) + sheet("S1,T,85,C")), "VALUE_MISMATCH")[0]; self.assertIn("5 C", f["detail"]); self.assertNotIn("%", f["detail"])

    def test_tolerances_decide_and_are_echoed(self):
        rows = D.rows_from_flowsheet("pid", fs(mass=1000.0)) + sheet("S1,mass_flow,1004,kg/h")
        self.assertEqual(of(D.check(rows, rel_tol=0.005), "VALUE_MISMATCH"), []); self.assertEqual(len(of(D.check(rows, rel_tol=0.003), "VALUE_MISMATCH")), 1)
        out = D.check(rows, rel_tol=0.003, temp_tol_C=2); self.assertEqual(out["tolerances"]["rel_tol"], 0.003); self.assertEqual(out["tolerances"]["temp_tol_C"], 2)
        t = D.rows_from_flowsheet("pid", fs(T=80)) + sheet("S1,T,80.4,C"); self.assertEqual(of(D.check(t), "VALUE_MISMATCH"), [])
        t = D.rows_from_flowsheet("pid", fs(T=80)) + sheet("S1,T,81,C"); self.assertEqual(len(of(D.check(t), "VALUE_MISMATCH")), 1); self.assertEqual(of(D.check(t, temp_tol_C=1.5), "VALUE_MISMATCH"), [])
        with self.assertRaises(ValueError): D.check(rows, rel_tol=-1)

    def test_type_and_text_mismatches_ignore_case_spaces_and_hyphens(self):
        rows = D.rows_from_flowsheet("pid", fs(utype="heater")) + sheet("E-100,type,Heat Exchanger,", "E-100,material,Carbon-Steel,", name="vendor") + sheet("E-100,material,carbon steel,", name="epc")
        out = D.check(rows); self.assertEqual([f["attribute"] for f in of(out, "TYPE_MISMATCH")], ["type"])
        self.assertEqual(of(out, "TEXT_MISMATCH"), [])                                                                 # same material in two spellings
        rows = sheet("E-100,material,SS316,", name="a") + sheet("E-100,material,CS,", name="b"); self.assertEqual(len(of(D.check(rows), "TEXT_MISMATCH")), 1)

    def test_duplicate_rows_in_one_source_conflict_only_when_they_differ(self):
        out = D.check(sheet("S1,T,80,C", "S1,T,90,C", name="a") + sheet("S1,T,80,C", name="b")); self.assertEqual(len(of(out, "DUPLICATE_CONFLICT")), 1)
        self.assertEqual(of(D.check(sheet("S1,T,80,C", "S1,T,80.1,C", name="a") + sheet("S1,T,80,C", name="b")), "DUPLICATE_CONFLICT"), [])

    def test_duplicates_in_different_units_that_cannot_be_compared_are_not_called_conflicts(self):
        out = D.check(sheet("E,area,10,m2", "E,area,10.76,ft2", name="a") + sheet("E,area,10,m2", name="b")); self.assertEqual(of(out, "DUPLICATE_CONFLICT"), [])

    def test_missing_items_are_informational_not_a_disagreement(self):
        out = D.check(D.rows_from_flowsheet("pid", fs()) + sheet("S9,T,50,C"))
        m = of(out, "MISSING_IN_SOURCE"); self.assertTrue({f["item"] for f in m} >= {"S1", "S9"}); self.assertTrue(out["agree"])
        self.assertIn("vendor", next(f for f in m if f["item"] == "S1" and f["attribute"] == "T")["detail"])

    def test_operating_above_design_in_the_same_item(self):
        out = D.check(sheet("V-1,operating_pressure,12,barg", "V-1,design_pressure,10,barg", "V-2,operating_temperature,100,C", "V-2,design_temperature,150,C", name="a") + sheet("V-1,design_pressure,10,barg", name="b"))
        f = of(out, "OPERATING_EXCEEDS_DESIGN"); self.assertEqual({x["item"] for x in f}, {"V-1"}); self.assertFalse(out["agree"])
        eq = D.check(sheet("V-1,operating_pressure,10,barg", "V-1,design_pressure,10,barg", name="a") + sheet("V-1,design_pressure,10,barg", name="b")); self.assertEqual(of(eq, "OPERATING_EXCEEDS_DESIGN"), [])
        mixed = D.check(sheet("V-1,operating_pressure,10.5,barg", name="a") + sheet("V-1,design_pressure,10.0,barg", name="b")); self.assertEqual(len(of(mixed, "OPERATING_EXCEEDS_DESIGN")), 1)    # across sources too

    def test_unreadable_units_are_reported_and_left_out(self):
        out = D.check(D.rows_from_flowsheet("pid", fs(P=300.0)) + sheet("S1,P,3,bar", "S1,T,80,furlongs", "S1,mass_flow,1000,", "S1,duty,5,widgets"))
        u = of(out, "UNIT_UNREADABLE"); self.assertEqual(sorted(x["attribute"] for x in u), ["P", "T", "duty", "mass_flow"])
        self.assertTrue(any("gauge vs abs" in x["detail"] for x in u)); self.assertEqual(of(out, "VALUE_MISMATCH"), [])                                    # nothing guessed, no comparison made

    def test_tolerance_boundary_and_larger_value_basis(self):
        rows = sheet("X,rating,100,kW", name="a") + sheet("X,rating,200,kW", name="b")
        self.assertEqual(of(D.check(rows, rel_tol=0.5), "VALUE_MISMATCH"), [])             # a 100 difference is exactly 50% of the larger value: not beyond tolerance
        self.assertEqual(of(D.check(rows, rel_tol=0.6), "VALUE_MISMATCH"), []); self.assertEqual(len(of(D.check(rows, rel_tol=0.49), "VALUE_MISMATCH")), 1)

    def test_operating_temperature_above_design(self):
        out = D.check(sheet("V-2,operating_temperature,160,C", "V-2,design_temperature,150,C", name="a") + sheet("V-2,design_temperature,150,C", name="b"))
        self.assertEqual({f["attribute"] for f in of(out, "OPERATING_EXCEEDS_DESIGN")}, {"operating_temperature"})

    def test_every_ambiguous_pressure_unit_is_refused_and_missing_or_nonfinite_values_are_explained(self):
        for u in ("bar", "kPa", "MPa", "Pa", "psi", "kg/cm2"):
            out = D.check(D.rows_from_flowsheet("pid", fs()) + sheet(f"S1,P,3,{u}")); self.assertEqual([f["attribute"] for f in of(out, "UNIT_UNREADABLE")], ["P"], u)
        for u in ("barg", "bara", "kPag", "kPaa", "psig", "psia", "atm"):
            self.assertEqual(of(D.check(D.rows_from_flowsheet("pid", fs()) + sheet(f"S1,P,3,{u}")), "UNIT_UNREADABLE"), [], u)
        out = D.check(D.rows_from_flowsheet("pid", fs()) + sheet("S1,mass_flow,5,", "S1,T,nan,C"))
        d = {f["attribute"]: f["detail"] for f in of(out, "UNIT_UNREADABLE")}; self.assertIn("needs a unit", d["mass_flow"]); self.assertIn("finite", d["T"])

    def test_other_numeric_attributes_compare_only_in_the_same_unit(self):
        a = D.rows_from_flowsheet("pid", fs(params={"UA": 5.0}))
        out = D.check(a + [{"source": "v", "item": "E-100", "attribute": "UA", "value": "5", "unit": "kW/K"}]); self.assertEqual(len(of(out, "UNITS_NOT_COMPARABLE")), 1)           # flowsheet params carry no unit
        b = [{"source": "v", "item": "E-100", "attribute": "area", "value": "10", "unit": "m2"}, {"source": "w", "item": "E-100", "attribute": "area", "value": "12", "unit": "m2"}]
        self.assertEqual(len(of(D.check(b), "VALUE_MISMATCH")), 1); b[1]["unit"] = "ft2"; self.assertEqual(len(of(D.check(b), "UNITS_NOT_COMPARABLE")), 1)

    def test_a_number_against_text_is_a_mismatch(self):
        out = D.check([{"source": "a", "item": "X", "attribute": "rating", "value": "150", "unit": "lb"}, {"source": "b", "item": "X", "attribute": "rating", "value": "Class 150", "unit": ""}]); self.assertEqual(len(of(out, "VALUE_MISMATCH")), 1)

    def test_three_sources_compare_pairwise(self):
        out = D.check(D.rows_from_flowsheet("pid", fs(mass=1000)) + D.rows_from_flowsheet("hmb", fs(mass=1000)) + sheet("S1,mass_flow,1100,kg/h"))
        self.assertEqual(sorted(tuple(v["source"] for v in f["values"]) for f in of(out, "VALUE_MISMATCH")), [("hmb", "vendor"), ("pid", "vendor")]); self.assertEqual(out["sources"], ["hmb", "pid", "vendor"])


class Reading(unittest.TestCase):
    def test_sheet_rows_need_item_attribute_value_and_accept_dicts(self):
        with self.assertRaisesRegex(ValueError, "missing value"): D.rows_from_datasheet("v", "item,attribute,value,unit\nS1,T,,C")
        r = D.rows_from_datasheet("v", [{"Item": " S1 ", "Attribute": "T", "Value": 80, "Unit": "C"}]); self.assertEqual((r[0]["item"], r[0]["value"], r[0]["unit"]), ("S1", "80", "C"))

    def test_flowsheet_rows_carry_streams_and_units(self):
        r = D.rows_from_flowsheet("pid", fs(params={"UA": 1.0})); self.assertEqual({(x["item"], x["attribute"]) for x in r}, {("S1", "T"), ("S1", "P"), ("S1", "mass_flow"), ("E-100", "type"), ("E-100", "UA")})


class ToolAndCli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.p = os.path.join(self.d, "v.csv")
        with open(self.p, "w") as fh: fh.write("item,attribute,value,unit\nS1,P,2.0,barg\nS1,T,80,C\n")

    def test_tool_compares_sessions_and_sheets(self):
        self.assertIn("datasheet_check", M.TOOLS)
        with mock.patch.dict(M.SESSIONS, {"p": fs(P=300.0)}):
            out = M.TOOLS["datasheet_check"][0]({"pid": "p", "sheets": [{"name": "vendor", "path": self.p}], "rel_tol": 0.001})
        self.assertEqual(len(of(out, "VALUE_MISMATCH")), 1); self.assertEqual(out["sources"], ["pid", "vendor"])

    def test_tool_argument_rules(self):
        f = M.TOOLS["datasheet_check"][0]
        with self.assertRaisesRegex(ValueError, "at least two"): f({"sheets": [{"name": "v", "path": self.p}]})
        with self.assertRaisesRegex(ValueError, "distinct"): f({"sheets": [{"name": "v", "path": self.p}, {"name": "v", "path": self.p}]})
        with self.assertRaisesRegex(ValueError, "not allowed"): f({"sheets": [{"name": "a", "path": self.p}, {"name": "b", "path": os.path.join(self.d, "x.txt")}]})
        with self.assertRaises(FileNotFoundError): f({"sheets": [{"name": "a", "path": self.p}, {"name": "b", "path": os.path.join(self.d, "missing.csv")}]})

    def test_tool_writes_nothing_and_changes_no_session(self):
        s = fs(); before = json.dumps(s.streams["S1"].__dict__, sort_keys=True)
        with mock.patch.dict(M.SESSIONS, {"p": s}): M.TOOLS["datasheet_check"][0]({"pid": "p", "sheets": [{"name": "vendor", "path": self.p}]})
        self.assertEqual(json.dumps(s.streams["S1"].__dict__, sort_keys=True), before); self.assertEqual(sorted(os.listdir(self.d)), ["v.csv"])

    def test_cli_exit_codes(self):
        j = os.path.join(self.d, "fs.json"); fs(P=301.325).to_json(j)
        self.assertEqual(D.main(["--pid", j, "--sheet", f"vendor={self.p}"]), 0)
        fs(P=500.0).to_json(j); self.assertEqual(D.main(["--pid", j, "--sheet", f"vendor={self.p}"]), 1)
        self.assertEqual(D.main(["--pid", j]), 2); self.assertEqual(D.main(["--bogus", "1"]), 2)


if __name__ == "__main__": unittest.main()
