"""units.py, ir.py, normalize.py and validate.py: tables, boundaries and branch behaviour."""
import json
import pytest

from hysys_bridge import normalize, units as U, validate
from hysys_bridge.ir import Flowsheet, Stream, Unit


# ---- units ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("v,u,want", [
    (25, "C", 25), (25, "degC", 25), (25, "°C", 25), (300, "K", 300 - 273.15), (212, "F", 100), (212, "°F", 100),
    (32, "degF", 0), (0, " c ", 0),
])
def test_to_celsius(v, u, want):
    assert U.to_celsius(v, u) == pytest.approx(want)


def test_to_celsius_unknown_unit():
    with pytest.raises(ValueError, match="unknown temperature unit 'r'"):
        U.to_celsius(1, "R")


@pytest.mark.parametrize("v,u,want", [
    (2.0, "barg", 2 * 100 + 101.325), (100, "kPag", 100 + 101.325), (1, "kg/cm2g", 98.0665 + 101.325),
    (1, "psig", 6.894757 + 101.325), (1, "MPag", 1000 + 101.325), (1, "bar", 100), (1, "bara", 100),
    (5, "kPa", 5), (5, "kPaa", 5), (1, "MPa", 1000), (1000, "Pa", 1), (1, "atm", 101.325), (1, "psia", 6.894757),
    (1, "kg/cm2", 98.0665), (1, "kg/cm²", 98.0665), (1, "kg/cm²g", 98.0665 + 101.325), (1, " BARG ", 100 + 101.325),
])
def test_to_kpa_abs(v, u, want):
    assert U.to_kpa_abs(v, u) == pytest.approx(want)


def test_gauge_uses_custom_atmosphere():
    assert U.to_kpa_abs(1, "barg", atm=90.0) == pytest.approx(190.0)
    assert U.to_kpa_abs(1, "bar", atm=90.0) == pytest.approx(100.0)       # absolute: atm ignored


@pytest.mark.parametrize("u", ["psi", "bar(g)", "foo", "", "g"])
def test_ambiguous_or_unknown_pressure_unit_raises(u):
    with pytest.raises(ValueError, match="unknown/ambiguous pressure unit"):
        U.to_kpa_abs(1, u)


def test_plain_barg_style_entry_with_no_base_rejected():
    # 'barg' sits in the table as None; it is only reachable through the gauge branch above
    assert U._P["barg"] is None


@pytest.mark.parametrize("fn,u,want", [
    (U.to_kg_h, "kg/h", 1), (U.to_kg_h, "t/h", 1000), (U.to_kg_h, "kg/s", 3600), (U.to_kg_h, "lb/h", 0.45359237),
    (U.to_kg_h, "kg/hr", 1), (U.to_kg_h, "tph", 1000), (U.to_kg_h, "T / H", 1000),
    (U.to_kmol_h, "kmol/h", 1), (U.to_kmol_h, "mol/h", 1e-3), (U.to_kmol_h, "kmol/hr", 1), (U.to_kmol_h, "lbmol/h", 0.45359237),
    (U.to_m3_h, "m3/h", 1), (U.to_m3_h, "l/h", 1e-3), (U.to_m3_h, "m3/s", 3600), (U.to_m3_h, "m³/hr", 1),
    (U.to_m3_h, "bbl/d", 0.158987 / 24),
    (U.to_kj_h, "kJ/h", 1), (U.to_kj_h, "MJ/h", 1e3), (U.to_kj_h, "kW", 3600), (U.to_kj_h, "GJ/h", 1e6),
    (U.to_kj_h, "kcal/h", 4.1868), (U.to_kj_h, "Btu/h", 1.055056),
])
def test_linear_tables(fn, u, want):
    assert fn(2.0, u) == pytest.approx(2 * want)


@pytest.mark.parametrize("fn,msg", [(U.to_kg_h, "mass-flow"), (U.to_kmol_h, "molar-flow"),
                                    (U.to_m3_h, "vol-flow"), (U.to_kj_h, "energy")])
def test_linear_unknown_unit_names_the_quantity(fn, msg):
    with pytest.raises(ValueError, match=f"unknown {msg} unit 'furlongs'"):
        fn(1, "furlongs")


# ---- ir ---------------------------------------------------------------------------------------------------
def make_fs():
    fs = Flowsheet(name="n", fluid_package="NRTL", components=["A", "B"])
    fs.units["P-1"] = Unit(id="P-1", type="pump", params={"dp": 1.5}, flags=["f"])
    fs.streams["1"] = Stream(id="1", kind="feed", dst="P-1", T_C=1.0, P_kPa=2.0, mass_flow_kg_h=3.0,
                             composition={"A": 0.4, "B": 0.6}, composition_basis="mass", checks={"vapour_fraction": 0.1},
                             source={"T": "x"}, confidence={"T": 0.9})
    fs.streams["2"] = Stream(id="2", kind="product", src="P-1")
    return fs


def test_json_roundtrip_preserves_everything(tmp_path):
    fs = make_fs(); fs.relink()
    p = str(tmp_path / "f.json"); fs.to_json(p)
    back = Flowsheet.from_json(p)
    assert back == fs
    raw = json.load(open(p))
    assert raw["name"] == "n" and raw["fluid_package"] == "NRTL" and raw["components"] == ["A", "B"]
    assert open(p).read().startswith('{\n  "name"')                  # indent=2


def test_relink_rebuilds_inlets_and_outlets():
    fs = make_fs()
    fs.units["P-1"].inlets = ["stale"]; fs.units["P-1"].outlets = ["stale"]
    fs.relink()
    assert fs.units["P-1"].inlets == ["1"] and fs.units["P-1"].outlets == ["2"]


def test_relink_ignores_unknown_endpoints_and_none():
    fs = make_fs()
    fs.streams["3"] = Stream(id="3", src="GHOST", dst="GHOST2")
    fs.relink()
    assert fs.units["P-1"].inlets == ["1"] and fs.units["P-1"].outlets == ["2"]


def test_stream_defaults_are_independent():
    a, b = Stream(id="a"), Stream(id="b")
    a.composition["x"] = 1.0; a.checks["c"] = 1.0
    assert b.composition == {} and b.checks == {} and a.composition_basis == "mole" and a.kind == "intermediate"


# ---- normalize --------------------------------------------------------------------------------------------
def two_into(utype):
    fs = Flowsheet()
    fs.units["X"] = Unit(id="X", type=utype)
    fs.streams["a"] = Stream(id="a", dst="X"); fs.streams["b"] = Stream(id="b", dst="X")
    fs.streams["o"] = Stream(id="o", src="X")
    return fs


@pytest.mark.parametrize("t", sorted(normalize.SINGLE_IN))
def test_single_inlet_units_get_a_mixer(t):
    fs = two_into(t)
    log = normalize.normalize(fs)
    assert log == [f"inserted mixer MX-X ahead of X (merged ['a', 'b'])"]
    assert fs.units["MX-X"].type == "mixer" and fs.units["MX-X"].inlets == ["a", "b"]
    assert fs.units["X"].inlets == ["MX-X-out"]
    s = fs.streams["MX-X-out"]
    assert (s.kind, s.src, s.dst) == ("intermediate", "MX-X", "X")
    assert fs.streams["a"].dst == "MX-X" and fs.streams["b"].dst == "MX-X"


@pytest.mark.parametrize("t", sorted(normalize.MULTI_IN))
def test_multi_inlet_units_are_left_alone(t):
    fs = two_into(t)
    assert normalize.normalize(fs) == [] and set(fs.units) == {"X"}


def test_single_inlet_is_left_alone():
    fs = Flowsheet()
    fs.units["P"] = Unit(id="P", type="pump")
    fs.streams["a"] = Stream(id="a", dst="P")
    assert normalize.normalize(fs) == [] and len(fs.units) == 1


def one_unit_two_out(t):
    fs = Flowsheet()
    fs.units["X"] = Unit(id="X", type=t)
    fs.streams["i"] = Stream(id="i", dst="X")
    fs.streams["a"] = Stream(id="a", src="X"); fs.streams["b"] = Stream(id="b", src="X")
    return fs


@pytest.mark.parametrize("t", ["pump", "heater", "cooler", "valve", "compressor", "mixer"])
def test_multi_outlet_non_splitters_get_a_splitter(t):
    fs = one_unit_two_out(t)
    assert normalize.normalize(fs) == ["inserted splitter SP-X after X"]
    sp = fs.units["SP-X"]
    assert sp.type == "splitter" and sp.outlets == ["a", "b"] and sp.inlets == ["SP-X-in"]
    assert fs.units["X"].outlets == ["SP-X-in"]
    assert (fs.streams["SP-X-in"].src, fs.streams["SP-X-in"].dst) == ("X", "SP-X")


@pytest.mark.parametrize("t", ["splitter", "separator", "column", "reactor", "expander"])
def test_units_that_may_have_many_outlets_are_untouched(t):
    fs = one_unit_two_out(t)
    assert normalize.normalize(fs) == [] and set(fs.units) == {"X"}


def test_unknown_units_are_flagged_once_per_run():
    fs = Flowsheet()
    fs.units["Z"] = Unit(id="Z", type="unknown")
    normalize.normalize(fs)
    assert fs.units["Z"].flags == ["unrecognised-symbol: engineer must assign type"]


def test_normalize_relinks_even_with_no_changes():
    fs = Flowsheet()
    fs.units["P"] = Unit(id="P", type="pump", inlets=["stale"])
    fs.streams["a"] = Stream(id="a", dst="P")
    normalize.normalize(fs)
    assert fs.units["P"].inlets == ["a"]


def test_mixer_then_splitter_on_same_unit():
    fs = two_into("pump")
    fs.streams["o2"] = Stream(id="o2", src="X")
    log = normalize.normalize(fs)
    assert log == ["inserted mixer MX-X ahead of X (merged ['a', 'b'])", "inserted splitter SP-X after X"]


# ---- validate ---------------------------------------------------------------------------------------------
def fsv(**kw):
    fs = Flowsheet(components=["A", "B"])
    fs.units["P"] = Unit(id="P", type="pump")
    fs.streams["1"] = Stream(id="1", kind="feed", dst="P", T_C=25, P_kPa=500, mass_flow_kg_h=100,
                             composition={"A": 0.5, "B": 0.5}, **kw)
    fs.streams["2"] = Stream(id="2", kind="product", src="P", mass_flow_kg_h=100)
    fs.relink()
    return fs


def msgs(fs, **kw): return [str(i) for i in validate.validate(fs, **kw)]


def test_clean_flowsheet_has_no_issues():
    assert validate.validate(fsv()) == []


def test_issue_str_format():
    assert str(validate.Issue("warn", "w", "m")) == "[WARN] w: m"


@pytest.mark.parametrize("T,bad", [(-273.15, True), (-273.14, False), (1999.9, False), (2000.0, True)])
def test_temperature_bounds_exclusive(T, bad):
    fs = fsv(); fs.streams["1"].T_C = T
    assert any("out of bounds" in m for m in msgs(fs)) is bad


@pytest.mark.parametrize("P,bad", [(0.0, True), (0.001, False), (4.9e5, False), (5e5, True)])
def test_pressure_bounds_exclusive(P, bad):
    fs = fsv(); fs.streams["1"].P_kPa = P
    assert any("kPa out of bounds" in m for m in msgs(fs)) is bad


def test_negative_flow_any_basis():
    for attr in ("mass_flow_kg_h", "molar_flow_kmol_h", "vol_flow_m3_h"):
        fs = fsv(); setattr(fs.streams["1"], attr, -0.1)
        assert "[ERROR] 1: negative flow" in msgs(fs)
    fs = fsv(); fs.streams["1"].mass_flow_kg_h = 0.0
    assert "negative flow" not in " ".join(msgs(fs))


def test_feed_requirements():
    fs = fsv(); fs.streams["1"].T_C = None
    assert "[ERROR] 1: feed missing T or P" in msgs(fs)
    fs = fsv(); fs.streams["1"].P_kPa = None
    assert "[ERROR] 1: feed missing T or P" in msgs(fs)
    fs = fsv(); fs.streams["1"].mass_flow_kg_h = None
    assert "[ERROR] 1: feed has no flow spec" in msgs(fs)
    fs = fsv(); fs.streams["1"].composition = {}
    assert "[ERROR] 1: feed has no composition" in msgs(fs)
    fs = fsv(); fs.streams["1"].kind = "intermediate"; fs.streams["1"].T_C = None
    assert "feed missing" not in " ".join(msgs(fs))


def test_composition_sum_tolerances():
    def issues(tot):
        fs = fsv(); fs.streams["1"].composition = {"A": tot, "B": 0.0}
        return [i for i in validate.validate(fs)]
    assert issues(1.0) == [] and issues(1.0005) == [] and issues(0.9995) == []       # inside comp_tol
    w = issues(0.99)
    assert [i.level for i in w] == ["warn"] and "composition sums to 0.99000 (basis=mole)" in w[0].msg
    assert [i.level for i in issues(0.979)] == ["error"]                               # beyond 0.02
    assert [i.level for i in issues(0.981)] == ["warn"]                                # within 0.02: warning only
    assert [i.level for i in issues(1.021)] == ["error"] and [i.level for i in issues(1.019)] == ["warn"]


def test_custom_comp_tol():
    fs = fsv(); fs.streams["1"].composition = {"A": 0.5, "B": 0.49}
    assert validate.validate(fs, comp_tol=0.02) == []
    assert validate.validate(fs, comp_tol=0.001)[0].level == "warn"


def test_negative_fraction_and_unknown_components():
    fs = fsv(); fs.streams["1"].composition = {"A": 1.2, "B": -0.2}
    assert "[ERROR] 1: negative fraction" in msgs(fs)
    fs = fsv(); fs.streams["1"].composition = {"A": 0.5, "C": 0.5}
    assert "[ERROR] 1: components not in list: ['C']" in msgs(fs)


def test_hysys_component_db_check():
    fs = fsv()
    assert validate.validate(fs, hysys_names={"A", "B"}) == []
    m = msgs(fs, hysys_names={"A"})
    assert m == ["[ERROR] 1: not in HYSYS component db (map them): ['B']"]
    assert validate.validate(fs, hysys_names=None) == []


def test_vapour_fraction_range():
    for vf, bad in ((0.0, False), (1.0, False), (-0.01, True), (1.01, True)):
        fs = fsv(); fs.streams["1"].checks["vapour_fraction"] = vf
        assert any("outside 0..1" in m for m in msgs(fs)) is bad


def test_dangling_endpoints():
    fs = fsv(); fs.streams["2"].src = "GHOST"
    assert "[ERROR] 2: dangling src/dst" in msgs(fs)
    fs = fsv(); fs.streams["2"].dst = "GHOST"
    assert "[ERROR] 2: dangling src/dst" in msgs(fs)
    assert not any("dangling" in m for m in msgs(fsv()))


def test_unit_checks():
    fs = fsv(); fs.units["P"].type = "unknown"
    assert "[ERROR] P: unit type unresolved" in msgs(fs)
    fs = fsv(); fs.units["Q"] = Unit(id="Q", type="separator")
    m = msgs(fs)
    assert "[WARN] Q: no inlet" in m and "[WARN] Q: no outlet" in m


@pytest.mark.parametrize("t", ["mixer", "heater", "cooler", "pump", "valve", "compressor"])
def test_mass_balance_checked_for_simple_units(t):
    fs = fsv(); fs.units["P"].type = t; fs.streams["2"].mass_flow_kg_h = 150
    assert any("mass balance: in 100.00 vs out 150.00 kg/h (+50.00%)" in m for m in msgs(fs))


@pytest.mark.parametrize("t", ["separator", "column", "reactor", "splitter"])
def test_mass_balance_not_checked_for_other_units(t):
    fs = fsv(); fs.units["P"].type = t; fs.streams["2"].mass_flow_kg_h = 150
    assert not any("mass balance" in m for m in msgs(fs))


def test_mass_balance_tolerance_boundary_and_override():
    fs = fsv(); fs.streams["2"].mass_flow_kg_h = 101.0                    # exactly 1%: not > mb_tol
    assert not any("mass balance" in m for m in msgs(fs))
    fs.streams["2"].mass_flow_kg_h = 101.5
    assert any("mass balance" in m for m in msgs(fs))
    assert not any("mass balance" in m for m in msgs(fs, mb_tol=0.02))


def test_mass_balance_skipped_when_a_flow_is_missing_or_zero_in():
    fs = fsv(); fs.streams["2"].mass_flow_kg_h = None
    assert not any("mass balance" in m for m in msgs(fs))
    fs = fsv(); fs.streams["1"].mass_flow_kg_h = 0.0; fs.streams["2"].mass_flow_kg_h = 5.0
    assert not any("mass balance" in m for m in msgs(fs))


def test_negative_mass_balance_sign():
    fs = fsv(); fs.streams["2"].mass_flow_kg_h = 50
    assert any("(-50.00%)" in m for m in msgs(fs))


def test_blocking_filters_errors_only():
    iss = [validate.Issue("warn", "a", "b"), validate.Issue("error", "c", "d")]
    assert validate.blocking(iss) == [iss[1]] and validate.blocking([]) == []
