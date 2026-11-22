"""valve_sizing.cli: every sub-command maps its flags onto the right function argument (checked against a direct call)."""
import json
import runpy
import sys
import warnings

import pytest

from valve_sizing import cli, control, pressure, relief


def run(capsys, *argv):
    assert cli.main(list(argv)) is None
    return capsys.readouterr().out


def test_levels_json(capsys):
    out = json.loads(run(capsys, "levels", "--mawp", "1000", "--set", "900", "--scenario", "multiple",
                         "--operating", "850", "--lsr", "0.8"))
    want = pressure.levels(1000, 900, "multiple", 850, 0.8).__dict__
    assert out == want
    assert out["hydrotest_min"] == pytest.approx(1040) and out["accumulation_pct"] == 16


def test_levels_defaults(capsys):
    out = json.loads(run(capsys, "levels", "--mawp", "1000"))
    assert (out["set_pressure"], out["scenario"], out["hydrotest_min"]) == (1000, "single", pytest.approx(1300))


def test_levels_fire_scenario(capsys):
    assert json.loads(run(capsys, "levels", "--mawp", "1000", "--scenario", "fire"))["relieving_gauge"] == pytest.approx(1210)


def test_gas(capsys):
    out = run(capsys, "gas", "--mawp", "1000", "--set", "950", "--scenario", "multiple", "--operating", "800",
              "--w", "10000", "--T", "400", "--mw", "28", "--k", "1.3", "--z", "0.9", "--backpressure", "150", "--kb", "0.8")
    want = relief.size_gas(10000, 400, 28, 1.3, 0.9, 1000, 950, "multiple", 150, kb=0.8, operating=800)
    assert out == str(want) + "\n"


def test_gas_defaults(capsys):
    out = run(capsys, "gas", "--mawp", "1000", "--w", "10000", "--T", "400", "--mw", "28", "--k", "1.3")
    assert out == str(relief.size_gas(10000, 400, 28, 1.3, 1.0, 1000)) + "\n"


def test_steam(capsys):
    out = run(capsys, "steam", "--mawp", "5000", "--set", "4800", "--scenario", "fire", "--operating", "4000",
              "--w", "10000", "--ksh", "0.9")
    assert out == str(relief.size_steam(10000, 5000, 4800, "fire", 0.9, operating=4000)) + "\n"


def test_liquid(capsys):
    out = run(capsys, "liquid", "--mawp", "1000", "--set", "900", "--scenario", "single", "--operating", "700",
              "--q", "20", "--sg", "0.9", "--visc", "50", "--backpressure", "100")
    assert out == str(relief.size_liquid(20, 0.9, 1000, 900, "single", 100, 50, operating=700)) + "\n"


def test_fire(capsys):
    out = run(capsys, "fire", "--area", "100", "--latent", "300", "--F", "0.5")
    assert out == str(relief.fire_vapour_rate(100, 300, 0.5, True)) + "\n"


def test_fire_poor_drainage_flag(capsys):
    out = run(capsys, "fire", "--area", "100", "--latent", "300", "--poor-drainage")
    assert out == str(relief.fire_vapour_rate(100, 300, 1.0, False)) + "\n"
    assert out != run(capsys, "fire", "--area", "100", "--latent", "300")


def test_control_liquid(capsys):
    out = run(capsys, "control-liquid", "--q", "100", "--p1", "10", "--p2", "5", "--sg", "1.0", "--pv", "1.0",
              "--pc", "100", "--FL", "0.8")
    assert out == str(control.liquid(100, 10, 5, 1.0, 1.0, 100, 0.8)) + "\n"


def test_control_liquid_default_FL(capsys):
    out = run(capsys, "control-liquid", "--q", "100", "--p1", "10", "--p2", "2.6", "--sg", "1.0", "--pv", "1.0", "--pc", "100")
    assert out == str(control.liquid(100, 10, 2.6, 1.0, 1.0, 100, 0.9)) + "\n" and "[CHOKED]" in out


def test_control_gas(capsys):
    out = run(capsys, "control-gas", "--w", "1000", "--p1", "10", "--p2", "5", "--T", "300", "--mw", "20", "--k", "1.4",
              "--z", "0.9", "--xT", "0.6")
    assert out == str(control.gas(1000, 10, 5, 300, 20, 1.4, 0.9, 0.6)) + "\n"


def test_missing_required_flag_exits_2(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["gas", "--mawp", "1000"])
    assert e.value.code == 2


def test_unknown_scenario_choice_exits_2():
    with pytest.raises(SystemExit) as e:
        cli.main(["levels", "--mawp", "1000", "--scenario", "bogus"])
    assert e.value.code == 2


def test_subcommand_required():
    with pytest.raises(SystemExit) as e:
        cli.main([])
    assert e.value.code == 2


def test_domain_errors_propagate(capsys):
    with pytest.raises(ValueError, match="exceeds 100% of MAWP"):
        cli.main(["levels", "--mawp", "1000", "--set", "1100"])


def test_module_main_guard(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["valve_sizing.cli", "levels", "--mawp", "1000"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(SystemExit) as e:
            runpy.run_module("valve_sizing.cli", run_name="__main__")
    assert e.value.code is None
    assert json.loads(capsys.readouterr().out)["mawp"] == 1000
