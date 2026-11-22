"""Boundaries and branches of valve_sizing.pressure / control / relief (pure maths, no I/O)."""
import math

import pytest

from valve_sizing import control, pressure, relief


# ---- pressure.levels --------------------------------------------------------------------------------------
class TestLevels:
    def test_defaults(self):
        lv = pressure.levels(1000)
        assert (lv.set_pressure, lv.scenario, lv.accumulation_pct) == (1000, "single", 10.0)
        assert lv.relieving_gauge == pytest.approx(1100) and lv.relieving_abs == pytest.approx(1100 + 101.325)
        assert lv.hydrotest_min == pytest.approx(1300) and lv.warnings == []

    def test_unknown_scenario_rejected(self):
        with pytest.raises(ValueError, match="scenario must be single|multiple|fire"):
            pressure.levels(1000, scenario="bogus")

    def test_fire_alias_maps_to_21_percent(self):
        lv = pressure.levels(1000, scenario="fire")
        assert lv.scenario == "fire_single_or_multiple" and lv.accumulation_pct == pytest.approx(21.0)
        assert lv.relieving_gauge == pytest.approx(1210)

    def test_lsr_scales_hydrotest(self):
        assert pressure.levels(1000, lsr=0.8).hydrotest_min == pytest.approx(1040)

    def test_set_pressure_cap_is_inclusive_at_mawp(self):
        pressure.levels(1000, 1000)                                  # exactly MAWP is fine
        pressure.levels(1000, 1000 + 1e-9)                           # the 1e-9 float tolerance is part of the contract
        with pytest.raises(ValueError, match="exceeds 100% of MAWP"):
            pressure.levels(1000, 1000.01)

    def test_supplemental_cap_is_105_percent(self):
        lv = pressure.levels(1000, 1050, "multiple", supplemental=True)
        assert lv.set_pressure == 1050
        with pytest.raises(ValueError, match="exceeds 105% of MAWP"):
            pressure.levels(1000, 1050.01, "multiple", supplemental=True)

    def test_supplemental_above_mawp_is_clamped_to_accumulation_limit(self):
        lv = pressure.levels(1000, 1050, "multiple", supplemental=True)
        assert lv.relieving_gauge == pytest.approx(1160)             # min(1050+160, 1000*1.16)
        assert any("above MAWP" in w for w in lv.warnings)

    def test_supplemental_with_single_scenario_warns(self):
        lv = pressure.levels(1000, 1000, "single", supplemental=True)
        assert any("only applies to multiple-valve" in w for w in lv.warnings)
        assert not any("only applies" in w for w in pressure.levels(1000, 1000, "multiple", supplemental=True).warnings)

    def test_low_set_pressure_adds_accumulation_on_mawp(self):
        lv = pressure.levels(1000, 900)
        assert lv.relieving_gauge == pytest.approx(1000)             # set + 10% of MAWP
        assert any("well below MAWP" in w for w in lv.warnings)

    def test_below_mawp_warning_threshold_is_99_percent(self):
        assert pressure.levels(1000, 990).warnings == []
        assert any("well below" in w for w in pressure.levels(1000, 989.9).warnings)
        # the warning is specific to the single-valve scenario
        assert pressure.levels(1000, 900, "multiple").warnings == []

    def test_operating_ratio_warning_threshold_is_90_percent(self):
        assert pressure.levels(1000, 1000, operating=900).warnings == []
        w = pressure.levels(1000, 1000, operating=950).warnings
        assert w == ["operating/set = 95%: above ~90% risks valve chatter/leakage; consider pilot-operated"]

    def test_operating_above_mawp_warns(self):
        w = pressure.levels(1000, 1000, operating=1000).warnings
        assert "operating pressure exceeds MAWP" not in w
        assert "operating pressure exceeds MAWP" in pressure.levels(1000, 1000, operating=1001).warnings

    def test_operating_none_adds_no_warning(self):
        assert pressure.levels(1000, 1000, operating=None).warnings == []


class TestThermal:
    def test_hand_calc(self):
        # q = beta*H/(rho*cp) m3/s -> *3600
        got = pressure.blocked_in_thermal_flow_m3_h(duty_kw=100, sg=1.0, cp_kj_kgK=2.1)
        assert got == pytest.approx(0.00074 * 100 / (1000 * 2.1) * 3600)

    def test_heat_kw_used_when_no_duty(self):
        assert pressure.blocked_in_thermal_flow_m3_h(heat_kw=50) == pytest.approx(
            pressure.blocked_in_thermal_flow_m3_h(duty_kw=50))

    def test_duty_overrides_heat(self):
        assert pressure.blocked_in_thermal_flow_m3_h(duty_kw=10, heat_kw=999) == pytest.approx(
            pressure.blocked_in_thermal_flow_m3_h(duty_kw=10))

    def test_zero_duty_is_not_replaced_by_heat(self):
        # `duty_kw is None` test, not truthiness: an explicit 0 wins over heat_kw
        assert pressure.blocked_in_thermal_flow_m3_h(duty_kw=0.0, heat_kw=50) == 0.0

    def test_density_and_beta_scale(self):
        base = pressure.blocked_in_thermal_flow_m3_h(duty_kw=100)
        assert pressure.blocked_in_thermal_flow_m3_h(duty_kw=100, sg=2.0) == pytest.approx(base / 2)
        assert pressure.blocked_in_thermal_flow_m3_h(duty_kw=100, beta_per_K=0.00148) == pytest.approx(base * 2)
        assert pressure.blocked_in_thermal_flow_m3_h() == 0.0


# ---- control valves ---------------------------------------------------------------------------------------
class TestControlLiquid:
    def test_kv_hand_calc_and_rating(self):
        r = control.liquid(100, 10, 5, 1.0, 1.0, 100)
        assert r.kv == pytest.approx(100 * math.sqrt(1.0 / 5))
        assert r.cv == pytest.approx(r.kv * 1.156) and r.rated_kv_recommended == pytest.approx(r.kv / 0.8)
        assert r.service == "liquid" and r.choked is False

    def test_fp_divides_kv(self):
        assert control.liquid(100, 10, 5, 1.0, 1.0, 100, fp=0.5).kv == pytest.approx(
            2 * control.liquid(100, 10, 5, 1.0, 1.0, 100).kv)

    def test_non_positive_dp_rejected(self):
        with pytest.raises(ValueError, match="p1 must exceed p2"):
            control.liquid(100, 5, 5, 1.0, 1.0, 100)
        with pytest.raises(ValueError, match="p1 must exceed p2"):
            control.liquid(100, 4, 5, 1.0, 1.0, 100)

    def test_choked_uses_choke_dp_and_notes(self):
        # FF = 0.96-0.28*sqrt(0.01) = 0.932 ; dP_choke = 0.9^2*(10-0.932) = 7.3451
        dpc = 0.81 * (10 - 0.932)
        r = control.liquid(100, 10, 10 - 7.4, 1.0, 1.0, 100)
        assert r.choked is True and r.kv == pytest.approx(100 * math.sqrt(1 / dpc))
        assert r.notes[0].startswith("choked/flashing-limited: dP 7.40 bar >= 7.35 bar")
        assert len(r.notes) == 1                                      # sigma note suppressed when choked

    def test_flashing_note_boundary_p2_equal_to_vapour_pressure(self):
        r = control.liquid(100, 2, 1.9, 1.0, 1.9, 100, FL=1.0)           # p2 == pv: not (yet) flashing
        assert r.choked is False and "downstream pressure below vapour pressure: flashing" not in r.notes

    def test_choke_boundary_is_inclusive(self):
        dpc = 0.81 * (10 - (0.96 - 0.28 * math.sqrt(0.01)) * 1.0)
        assert control.liquid(100, 10, 10 - dpc, 1.0, 1.0, 100).choked is True
        assert control.liquid(100, 10, 10 - dpc + 1e-6, 1.0, 1.0, 100).choked is False

    def test_sigma_note_threshold(self):
        # sigma = (p1-pv)/dp : 9/5 = 1.8 -> note ; 9/4.5 = 2.0 -> no note
        assert control.liquid(100, 10, 5, 1.0, 1.0, 100).notes == [
            "cavitation index sigma=1.80 < 2: incipient cavitation likely"]
        assert control.liquid(100, 10, 5.5, 1.0, 1.0, 100).notes == []

    def test_flashing_note_when_p2_below_vapour_pressure(self):
        r = control.liquid(100, 2, 1.85, 1.0, 1.9, 100, FL=1.0)
        assert r.choked is False
        assert r.notes[0] == "downstream pressure below vapour pressure: flashing"
        assert r.notes[1].startswith("cavitation index sigma=0.67")

    def test_str_not_choked(self):
        s = str(control.liquid(100, 10, 5.5, 1.0, 1.0, 100))
        assert s.startswith("liquid: Kv = 47.140 m3/h, Cv = 54.494  [not choked]  -> select rated Kv >= 58.93 ")
        assert "NOTE" not in s and s.endswith("(sized so the calc is ~80% of rated)")

    def test_str_choked_with_notes(self):
        s = str(control.liquid(100, 10, 2.6, 1.0, 1.0, 100))
        assert "[CHOKED]" in s and "[not choked]" not in s
        assert s.count("\n  NOTE: ") == 1


class TestControlGas:
    def test_hand_calc_not_choked(self):
        # x = 0.5, Fk = 1, xT = 0.7, Y = 1 - 0.5/(3*0.7)
        r = control.gas(1000, 10, 5, 300, 20, 1.4)
        Y = 1 - 0.5 / 2.1
        assert r.kv == pytest.approx(1000 / (94.8 * 10 * Y) * math.sqrt(300 / (0.5 * 20)))
        assert r.choked is False and r.notes == [] and r.service == "gas"

    def test_high_drop_note_threshold_is_x_above_half(self):
        assert control.gas(1000, 10, 5, 300, 20, 1.4).notes == []                      # x = 0.5 exactly
        assert control.gas(1000, 10, 4.9, 300, 20, 1.4).notes == ["dP/P1 = 0.51: high drop, check noise"]

    def test_choked_flow_uses_two_thirds(self):
        r = control.gas(1000, 10, 2, 300, 20, 1.4)                  # x = 0.8 >= 0.7
        assert r.choked is True and r.notes == ["choked flow: flow no longer rises with lower p2; noise check required"]
        assert r.kv == pytest.approx(1000 / (94.8 * 10 * (2 / 3)) * math.sqrt(300 / (0.7 * 20)))

    def test_choke_boundary_inclusive(self):
        assert control.gas(1000, 10, 3, 300, 20, 1.4).choked is True                   # x == xT*Fk
        assert control.gas(1000, 10, 3.01, 300, 20, 1.4).choked is False

    def test_k_scales_choke_limit(self):
        # Fk = k/1.4 : k=1.2 -> x_choke = 0.6
        assert control.gas(1000, 10, 4, 300, 20, 1.2).choked is True
        assert control.gas(1000, 10, 4.1, 300, 20, 1.2).choked is False

    def test_z_fp_and_xt_arguments_are_used(self):
        base = control.gas(1000, 10, 5, 300, 20, 1.4).kv
        assert control.gas(1000, 10, 5, 300, 20, 1.4, z=0.81).kv == pytest.approx(base * 0.9)
        assert control.gas(1000, 10, 5, 300, 20, 1.4, fp=0.5).kv == pytest.approx(base * 2)
        assert control.gas(1000, 10, 5, 300, 20, 1.4, xT=0.4).choked is True

    def test_non_positive_drop_rejected(self):
        with pytest.raises(ValueError, match="p1 must exceed p2"):
            control.gas(1000, 10, 10, 300, 20, 1.4)


class TestControlSteam:
    def test_hand_calc(self):
        r = control.steam(1000, 10, 5, 5.0)
        Y = 1 - 0.5 / (3 * (1.3 / 1.4) * 0.7)
        assert r.kv == pytest.approx(1000 / (31.6 * Y * math.sqrt(0.5 * 10 * 5.0)))
        assert (r.service, r.choked, r.notes) == ("steam/vapour", False, [])
        assert r.cv == pytest.approx(r.kv * 1.156) and r.rated_kv_recommended == pytest.approx(r.kv / 0.8)

    def test_choked(self):
        r = control.steam(1000, 10, 1, 5.0)
        xc = 1.3 / 1.4 * 0.7
        assert r.choked is True and r.notes == ["choked flow"]
        assert r.kv == pytest.approx(1000 / (31.6 * (2 / 3) * math.sqrt(xc * 10 * 5.0)))

    def test_choke_boundary_and_fp(self):
        xc = 1.3 / 1.4 * 0.7
        assert control.steam(1000, 10, 10 * (1 - xc), 5.0).choked is True
        assert control.steam(1000, 10, 10 * (1 - xc) + 0.01, 5.0).choked is False
        assert control.steam(1000, 10, 5, 5.0, fp=0.5).kv == pytest.approx(2 * control.steam(1000, 10, 5, 5.0).kv)

    def test_non_positive_drop_rejected(self):
        with pytest.raises(ValueError, match="p1 must exceed p2"):
            control.steam(1000, 5, 5, 5.0)


# ---- relief valves ----------------------------------------------------------------------------------------
class TestOrifice:
    def test_exact_area_selects_that_letter(self):
        assert relief.pick_orifice(0.110) == ("D", 0.110)
        assert relief.pick_orifice(0.111) == ("E", 0.196)
        assert relief.pick_orifice(26.0) == ("T", 26.0)

    def test_oversize_returns_none(self):
        assert relief.pick_orifice(26.01) == (None, None)

    def test_finish_counts_t_orifices(self):
        assert relief._finish("x", 26.01, pressure.levels(1000), {}, []).warnings == ["needs 2 x T orifice (or larger non-API valve)"]
        assert relief._finish("x", 52.0, pressure.levels(1000), {}, []).warnings == ["needs 2 x T orifice (or larger non-API valve)"]
        assert relief._finish("x", 52.1, pressure.levels(1000), {}, []).warnings == ["needs 3 x T orifice (or larger non-API valve)"]
        r = relief._finish("x", 0.1, pressure.levels(1000), {}, [])
        assert r.orifice == "D" and r.orifice_mm2 == pytest.approx(0.110 * 645.16) and r.warnings == []


class TestSteamKn:
    def test_below_1500_is_unity(self):
        assert relief.steam_kn(100) == 1.0 and relief.steam_kn(1500) == 1.0

    def test_correlation_between_1500_and_3200(self):
        assert relief.steam_kn(2000) == pytest.approx((0.1906 * 2000 - 1000) / (0.2292 * 2000 - 1061))
        assert relief.steam_kn(3200) == pytest.approx(1.19087, abs=1e-4)

    def test_above_3200_rejected(self):
        with pytest.raises(ValueError, match="only valid to 3200 psia"):
            relief.steam_kn(3200.01)


class TestSteamSizing:
    def test_low_pressure_warning_boundary_is_15_psia(self, monkeypatch):
        monkeypatch.setattr(relief, "PSI_PER_KPA", 1.0)
        for p1, warned in ((15.0, False), (14.999, True)):
            fake = pressure.Levels(100, 100, "single", 0.0, p1, 10.0, 130.0, [])
            monkeypatch.setattr(relief, "levels", lambda *a, _f=fake, **k: _f)
            assert bool(relief.size_steam(100, 100).warnings) is warned

    def test_low_pressure_warning(self):
        # relieving pressure just under 15 psia: MAWP 0 kPag -> P1 = (0 + 101.325)*0.145 = 14.7
        r = relief.size_steam(100, mawp=0.0)
        assert r.warnings == ["relieving pressure below ~15 psia: equation outside range"]

    def test_normal_pressure_has_no_warning_and_uses_kn(self):
        r = relief.size_steam(10000, 5000)
        assert r.warnings == [] and r.detail["Kn"] == 1.0 and r.orifice == "H"

    def test_high_pressure_applies_kn_and_ksh(self):
        # MAWP 15000 kPag -> relieving 16500 kPag = 2394 psia (> 1500) -> Kn != 1
        r = relief.size_steam(10000, 15000, ksh=0.9)
        P1 = r.detail["P1_psia"]
        assert 1500 < P1 < 3200 and r.detail["Kn"] == pytest.approx(relief.steam_kn(P1)) and r.detail["Kn"] != 1.0
        assert r.required_in2 == pytest.approx(10000 * 2.20462262 / (51.5 * P1 * 0.975 * r.detail["Kn"] * 0.9))

    def test_too_high_pressure_rejected(self):
        with pytest.raises(ValueError):
            relief.size_steam(10000, 25000)

    def test_kd_kb_kc_all_divide_area(self):
        a = relief.size_steam(10000, 5000).required_in2
        assert relief.size_steam(10000, 5000, kd=0.5).required_in2 == pytest.approx(a * 0.975 / 0.5)
        assert relief.size_steam(10000, 5000, kb=0.5).required_in2 == pytest.approx(a * 2)
        assert relief.size_steam(10000, 5000, kc=0.5).required_in2 == pytest.approx(a * 2)


class TestGasSizing:
    def test_critical_hand_calc(self):
        r = relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000)
        P1 = 1100 + 101.325
        P1 *= 0.145037738
        assert r.detail["regime"] == "critical"
        assert r.required_in2 == pytest.approx(10000 * 2.20462262 / (relief.gas_C(1.3) * 0.975 * P1) * math.sqrt(400 * 1.8 / 28))

    def test_regime_switch_at_critical_ratio(self):
        rc = relief.critical_ratio(1.3)
        P1_kpa = 1100 + 101.325
        def bp_for(r): return r * P1_kpa - 101.325
        assert relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, backpressure=bp_for(rc - 0.001)).detail["regime"] == "critical"
        assert relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, backpressure=bp_for(rc + 0.001)).detail["regime"] == "subcritical"

    def test_subcritical_warns_and_ignores_kb(self):
        a = relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, backpressure=900, kb=1.0)
        b = relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, backpressure=900, kb=0.7)
        assert a.required_in2 == pytest.approx(b.required_in2)
        assert a.warnings[0] == "subcritical flow: a balanced-bellows or pilot valve is usually needed; kb not applied (F2 covers it)"
        assert a.warnings[1].startswith("back pressure 90% of set > 10%")
        assert "F2" in a.detail

    def test_kb_applies_in_critical_flow(self):
        a = relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000).required_in2
        assert relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, kb=0.5).required_in2 == pytest.approx(2 * a)
        assert relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, kc=0.5).required_in2 == pytest.approx(2 * a)
        assert relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, kd=0.4875).required_in2 == pytest.approx(2 * a)

    def test_regime_boundary_is_inclusive_at_critical_ratio(self, monkeypatch):
        lv = pressure.levels(1000)
        P1 = lv.relieving_abs * relief.PSI_PER_KPA
        r = (200 + relief.ATM) * relief.PSI_PER_KPA / P1
        monkeypatch.setattr(relief, "critical_ratio", lambda k: r)       # r == critical ratio exactly
        assert relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, backpressure=200).detail["regime"] == "critical"
        monkeypatch.setattr(relief, "critical_ratio", lambda k: r - 1e-12)
        assert relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, backpressure=200).detail["regime"] == "subcritical"

    def test_backpressure_percentage_warning_threshold(self):
        # 10% of set (1000) = 100 kPag -> no warning ; above -> warning (if kb == 1)
        assert not any("back pressure" in w for w in relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, backpressure=100).warnings)
        w = relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, backpressure=150).warnings
        assert any(x.startswith("back pressure 15% of set > 10%") for x in w)
        # a balanced-bellows kb != 1 silences it
        assert not any("back pressure" in w for w in
                       relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, backpressure=150, kb=0.9).warnings)

    def test_zero_set_pressure_gives_zero_backpressure_percent(self):
        # set 0 -> relieving 100 kPag; the percentage is guarded against dividing by the zero set pressure
        r = relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, set_pressure=0.0, backpressure=50)
        assert not any("back pressure" in w for w in r.warnings)
        r = relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, set_pressure=1.0, backpressure=50)
        assert any("back pressure 5000% of set" in w for w in r.warnings)

    def test_z_warning_bounds(self):
        ok = lambda z: not any("Z=" in w for w in relief.size_gas(10000, 400, 28, 1.3, z, 1000).warnings)
        assert ok(1.0) and ok(1.2) and ok(0.01)
        assert not ok(1.21)
        assert not ok(0.0)                                           # boundary `z <= 0` is flagged

    def test_backpressure_above_relieving_is_rejected(self):
        with pytest.raises(ValueError):
            relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, backpressure=2000)

    @pytest.mark.xfail(strict=True, raises=ZeroDivisionError,
                       reason="size_gas: back pressure exactly equal to the relieving pressure gives r == 1 and "
                              "(1 - r) == 0 in the F2 term; size_liquid rejects the equivalent input with ValueError")
    def test_backpressure_equal_to_relieving_is_a_value_error(self):
        with pytest.raises(ValueError):
            relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, backpressure=1100)

    def test_scenario_changes_relieving_pressure_and_area(self):
        s = relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, scenario="single").required_in2
        f = relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, scenario="fire").required_in2
        assert f < s                                                 # higher relieving pressure -> smaller area


class TestLiquidSizing:
    def test_non_positive_dp_rejected(self):
        with pytest.raises(ValueError, match="backpressure >= relieving pressure"):
            relief.size_liquid(20, 1.0, 1000, backpressure=1100)
        with pytest.raises(ValueError):
            relief.size_liquid(20, 1.0, 1000, backpressure=1200)

    def test_viscosity_warning_threshold(self):
        assert relief.size_liquid(20, 1.0, 1000, viscosity_cP=100).warnings == []
        assert relief.size_liquid(20, 1.0, 1000, viscosity_cP=101).warnings == ["viscosity > 100 cP: confirm with manufacturer sizing"]

    def test_backpressure_reduces_dp_and_increases_area(self):
        a = relief.size_liquid(20, 1.0, 1000).required_in2
        b = relief.size_liquid(20, 1.0, 1000, backpressure=500).required_in2
        assert b > a

    def test_kw_kc_kd_scale_area(self):
        # not exactly 2x: the viscosity factor Kv is re-iterated on the new area's Reynolds number
        a = relief.size_liquid(20, 1.0, 1000).required_in2
        for kw in ({"kw": 0.5}, {"kc": 0.5}, {"kd": 0.325}):
            assert relief.size_liquid(20, 1.0, 1000, **kw).required_in2 == pytest.approx(2 * a, rel=5e-3)

    def test_viscosity_iteration_converges_to_a_fixed_point(self):
        r = relief.size_liquid(20, 1.0, 1000)
        a = 20 * 4.40286754 / (38.0 * 0.65 * r.detail["Kv"]) * math.sqrt(1.0 / r.detail["dP_psi"])
        assert r.required_in2 == pytest.approx(a, rel=1e-6)
        r = relief.size_liquid(20, 0.9, 1000, viscosity_cP=2000)
        a = 20 * 4.40286754 / (38.0 * 0.65 * r.detail["Kv"]) * math.sqrt(0.9 / r.detail["dP_psi"])
        assert r.required_in2 == pytest.approx(a, rel=1e-6)

    def test_detail_reports_dp_and_reynolds(self):
        r = relief.size_liquid(20, 1.0, 1000)
        assert r.detail["dP_psi"] == pytest.approx(1100 * 0.145037738)
        assert r.detail["Re"] > 0 and 0.9 < r.detail["Kv"] < 1.1


class TestFire:
    def test_hand_calc_adequate_drainage(self):
        r = relief.fire_vapour_rate(100.0, 300.0)
        q = 43.2 * 100.0 ** 0.82
        assert r["Q_kW"] == pytest.approx(q) and r["W_kg_h"] == pytest.approx(q / 300.0 * 3600)

    def test_poor_drainage_uses_higher_constant(self):
        a = relief.fire_vapour_rate(100.0, 300.0)["Q_kW"]
        b = relief.fire_vapour_rate(100.0, 300.0, adequate_drainage_and_firefighting=False)["Q_kW"]
        assert b == pytest.approx(a * 70.9 / 43.2)

    def test_env_factor_scales(self):
        assert relief.fire_vapour_rate(50.0, 200.0, env_factor=0.5)["Q_kW"] == pytest.approx(
            0.5 * relief.fire_vapour_rate(50.0, 200.0)["Q_kW"])

    def test_area_limit_is_260_inclusive(self):
        relief.fire_vapour_rate(260.0, 300.0)
        with pytest.raises(ValueError, match="A>260 m2"):
            relief.fire_vapour_rate(260.01, 300.0)


class TestResultStr:
    def test_str_has_orifice_levels_detail_and_warnings(self):
        r = relief.size_steam(10000, 5000, operating=4900)
        s = str(r)
        lines = s.splitlines()
        assert lines[0] == "steam: required area 348.7 mm2 (0.540 in2) -> orifice H (506 mm2)"
        assert lines[1] == "  MAWP 5000 kPag | set 5000 | relieving 5500.0 kPag (10% accumulation)"
        assert "  P1_psia = 812.4" in lines and "  Kn = 1" in lines      # float via .4g, int/other via plain
        assert lines[-1].startswith("  WARNING: operating/set = 98%")

    def test_str_for_oversize_says_none(self):
        s = str(relief.size_gas(1e6, 400, 28, 1.3, 1.0, 1000))
        assert "-> orifice NONE - exceeds T; use multiple valves" in s
        assert "  WARNING: needs 8 x T orifice (or larger non-API valve)" in s
        assert "  regime = critical" in s                              # non-float detail printed as is

    def test_result_warnings_precede_level_warnings(self):
        r = relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000, set_pressure=800, backpressure=800)
        warns = [l for l in str(r).splitlines() if l.startswith("  WARNING")]
        assert "subcritical" in warns[0] and "well below MAWP" in warns[-1]
