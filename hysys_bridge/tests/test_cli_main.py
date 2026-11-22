"""hysys_bridge.cli.main: every exit code and branch, with the HYSYS layer faked (no COM, no files outside tmp_path)."""
import csv
import json
import os
import runpy
import sys
import warnings

import pytest

from hysys_bridge import backend, cli, dexpi_export, extract_hmb, ocr, pid_extract, pid_reconcile
from hysys_bridge.backend import MockHysys
from hysys_bridge.ir import Flowsheet, Stream, Unit

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample", "hmb.csv")


@pytest.fixture
def out(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # review.csv / ocr_rows.csv are written to the CWD
    return tmp_path


def run(out, *args, mock=True):
    argv = [SAMPLE, "--out", str(out / "case.json"), "--audit", str(out / "audit.csv"), *args]
    if mock:
        argv.append("--mock")
    return cli.main(argv)


def test_mock_run_success(out, capsys):
    rc = run(out)
    text = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert text[0] == f"wrote 12 values, 0 read-back mismatches -> {out / 'audit.csv'}"
    assert text[1] == "post-solve: 12 H&MB disagreements"      # mock backend calculates nothing
    assert len(text) == 2 + 12                                  # one line per disagreement
    fs = Flowsheet.from_json(str(out / "case.json"))
    assert fs.fluid_package == "Peng-Robinson"                  # --package default
    assert set(fs.streams) == {"1", "2", "3", "4"}
    rows = list(csv.reader(open(out / "audit.csv")))
    assert rows[0] == ["stream", "prop", "source", "extracted", "readback", "status"]
    assert len(rows) == 13 and {r[5] for r in rows[1:]} == {"OK"}


def test_package_option_is_applied(out):
    assert run(out, "--package", "NRTL") == 0
    assert json.load(open(out / "case.json"))["fluid_package"] == "NRTL"


def test_default_output_names_are_case_json_and_audit_csv(out):
    assert cli.main([SAMPLE, "--mock"]) == 0
    assert (out / "case.json").exists() and (out / "audit.csv").exists()


def test_validation_error_blocks_with_exit_2(out, capsys):
    bad = out / "bad.csv"
    bad.write_text("Stream No.,1,2\nFrom,-,P-1\nTo,P-1,-\nTemperature (C),25,30\nPressure (kPa),500,400\n"
                   "Mass flow (kg/h),100,100\nComposition (mol%)\nA,50,100\n")
    rc = cli.main([str(bad), "--mock", "--out", str(out / "c.json"), "--audit", str(out / "a.csv")])
    text = capsys.readouterr().out
    assert rc == 2
    assert "[ERROR] 1: composition sums to 0.50000 (basis=mole)" in text
    assert "BLOCKED: fix 1 error(s); IR saved to " + str(out / "c.json") + " for review" in text
    assert (out / "c.json").exists()                      # IR is saved even when blocked
    assert not (out / "a.csv").exists()                   # nothing was written to the backend


def test_warnings_do_not_block(out, capsys):
    f = out / "warn.csv"
    f.write_text("Stream No.,1,2\nFrom,-,P-1\nTo,P-1,-\nTemperature (C),25,25\nPressure (kPa),500,500\n"
                 "Mass flow (kg/h),100,100\nComposition (mol%)\nA,99.5,100\n")      # sums to 0.995 -> warning only
    rc = cli.main([str(f), "--mock", "--out", str(out / "c.json"), "--audit", str(out / "a.csv")])
    text = capsys.readouterr().out
    assert rc == 0 and "[WARN] 1: composition sums to 0.99500" in text


def test_readback_mismatch_exits_3(out, capsys, monkeypatch):
    monkeypatch.setattr(cli, "MockHysys", lambda: MockHysys(corrupt=lambda sid, prop, v: v * 2 if prop == "T" else v))
    rc = run(out)
    text = capsys.readouterr().out
    assert rc == 3
    assert "wrote 12 values, 3 read-back mismatches" in text      # 3 temperatures written (feeds 1, 2 + outlet 4)
    assert "post-solve" not in text                               # never solves after a mismatch
    statuses = {(r[0], r[1]): r[5] for r in list(csv.reader(open(out / "audit.csv")))[1:]}
    assert statuses[("1", "T")] == "MISMATCH" and statuses[("1", "P")] == "OK"


def test_solve_false_skips_hmb_check(out, capsys, monkeypatch):
    class NoSolve(MockHysys):
        def solve(self): return False
    monkeypatch.setattr(cli, "MockHysys", NoSolve)
    assert run(out) == 0
    assert "post-solve" not in capsys.readouterr().out


def test_hmb_agreement_reports_zero_disagreements(out, capsys, monkeypatch):
    calc = {}
    fs = extract_hmb.from_csv(SAMPLE)
    for s in fs.streams.values():
        for k, v in (("T", s.T_C), ("P", s.P_kPa), ("mass", s.mass_flow_kg_h), ("vf", s.checks.get("vapour_fraction"))):
            if v is not None: calc[(s.id, k)] = v
    class Calc(MockHysys):
        def __init__(self): super().__init__(calc=calc)
        def get_comp(self, sid):
            return {"Water": {"1": 1.0, "2": 0.0, "3": 0.666, "4": 0.666}[sid],
                    "Ethanol": {"1": 0.0, "2": 1.0, "3": 0.334, "4": 0.334}[sid]}
    monkeypatch.setattr(cli, "MockHysys", Calc)
    assert run(out) == 0
    text = capsys.readouterr().out
    assert "post-solve: 0 H&MB disagreements" in text


def test_non_mock_uses_hysys_com_backend(out, capsys, monkeypatch):
    made = []
    class FakeCOM(MockHysys):
        def __init__(self): super().__init__(); made.append(self)
    monkeypatch.setattr(backend, "HysysCOM", FakeCOM)             # the real COM class is never touched
    assert run(out, mock=False) == 0
    assert len(made) == 1 and made[0].streams == {"1", "2", "3", "4"}


def test_mock_flag_does_not_construct_com(out, monkeypatch):
    def boom(*a, **k): raise AssertionError("HysysCOM must not be built with --mock")
    monkeypatch.setattr(backend, "HysysCOM", boom)
    assert run(out) == 0


def test_pdf_extension_is_case_insensitive_and_routes_to_from_pdf(out, monkeypatch):
    seen = {}
    real = extract_hmb.from_csv
    def fake_pdf(path, **kw):
        seen["pdf"] = path
        return real(SAMPLE)
    monkeypatch.setattr(extract_hmb, "from_pdf", fake_pdf)
    monkeypatch.setattr(extract_hmb, "from_csv", lambda p: (_ for _ in ()).throw(AssertionError("csv path used")))
    rc = cli.main(["REPORT.PDF", "--mock", "--out", str(out / "c.json"), "--audit", str(out / "a.csv")])
    assert rc == 0 and seen["pdf"] == "REPORT.PDF"


def test_csv_extension_routes_to_from_csv(out, monkeypatch):
    seen = {}
    real = extract_hmb.from_csv
    monkeypatch.setattr(extract_hmb, "from_csv", lambda p: seen.setdefault("p", p) and real(SAMPLE))
    monkeypatch.setattr(extract_hmb, "from_pdf", lambda p: (_ for _ in ()).throw(AssertionError("pdf path used")))
    assert cli.main(["x.csv", "--mock", "--out", str(out / "c.json"), "--audit", str(out / "a.csv")]) == 0
    assert seen["p"] == "x.csv"


# ---- scanned / OCR ----------------------------------------------------------------------------------------
OCR_ROWS = [["Stream No.", "1", "2"], ["From", "-", "P-1"], ["To", "P-1", "-"], ["Temperature (C)", "25", "30"],
            ["Pressure (kPa)", "500", "400"], ["Mass flow (kg/h)", "100", "100"],
            ["Composition (mol%)", "", ""], ["A", "100", "100"]]


def test_scanned_with_low_confidence_cells_blocks_exit_4(out, capsys, monkeypatch):
    monkeypatch.setattr(ocr, "ocr_pdf", lambda p: (OCR_ROWS, [(3, 1, "2S", 60.0), (4, 2, "4OO", 70.0)]))
    rc = cli.main(["scan.pdf", "--scanned", "--mock", "--out", str(out / "c.json"), "--audit", str(out / "a.csv")])
    text = capsys.readouterr().out
    assert rc == 4
    assert "BLOCKED: 2 low-confidence OCR cells -> review.csv." in text
    assert list(csv.reader(open(out / "review.csv"))) == [["row", "col", "text", "conf"], ["3", "1", "2S", "60.0"], ["4", "2", "4OO", "70.0"]]
    assert list(csv.reader(open(out / "ocr_rows.csv"))) == OCR_ROWS
    assert not (out / "c.json").exists()                          # blocked before anything else is produced


def test_scanned_accept_review_continues(out, capsys, monkeypatch):
    seen = {}
    real = extract_hmb.from_rows
    def spy(rows, **kw):
        seen["origin"] = kw.get("origin"); return real(rows, **kw)
    monkeypatch.setattr(extract_hmb, "from_rows", spy)
    monkeypatch.setattr(ocr, "ocr_pdf", lambda p: (OCR_ROWS, [(3, 1, "2S", 60.0)]))
    rc = cli.main(["scan.pdf", "--scanned", "--accept-review", "--mock", "--out", str(out / "c.json"), "--audit", str(out / "a.csv")])
    assert rc == 0 and seen["origin"] == "scan.pdf"
    assert (out / "review.csv").exists()


def test_scanned_clean_ocr_needs_no_acceptance(out, monkeypatch):
    monkeypatch.setattr(ocr, "ocr_pdf", lambda p: (OCR_ROWS, []))
    rc = cli.main(["scan.pdf", "--scanned", "--mock", "--out", str(out / "c.json"), "--audit", str(out / "a.csv")])
    assert rc == 0
    assert list(csv.reader(open(out / "review.csv"))) == [["row", "col", "text", "conf"]]


# ---- P&ID path --------------------------------------------------------------------------------------------
def topology(extra_stream=None, flagged=True):
    fs = Flowsheet(name="pid")
    for uid, t in (("MX-100", "mixer"), ("E-100", "heater")):
        fs.units[uid] = Unit(id=uid, type=t, flags=["needs-signoff"] if flagged else [])
    for sid, src, dst in (("1", None, "MX-100"), ("2", None, "MX-100"), ("3", "MX-100", "E-100"), ("4", "E-100", None)):
        fs.streams[sid] = Stream(id=sid, src=src, dst=dst,
                                 kind="feed" if src is None else ("product" if dst is None else "intermediate"))
    if extra_stream:
        fs.streams[extra_stream.id] = extra_stream
    fs.relink()
    return fs


def test_pid_draft_blocks_exit_5_and_writes_topology(out, capsys, monkeypatch):
    monkeypatch.setattr(pid_extract, "extract", lambda p: topology())
    rc = run(out, "--pid", "d.png")
    text = capsys.readouterr().out
    assert rc == 5
    assert "BLOCKED: P&ID topology is a draft (2 units); review " + str(out / "case.json") in text
    assert Flowsheet.from_json(str(out / "case.json")).units["E-100"].flags == ["needs-signoff"]
    assert not (out / "audit.csv").exists()


def test_pid_accept_topology_merges_values_and_runs(out, capsys, monkeypatch):
    monkeypatch.setattr(pid_extract, "extract", lambda p: topology())
    rc = run(out, "--pid", "d.png", "--accept-topology")
    text = capsys.readouterr().out
    assert rc == 0
    assert "wrote 12 values, 0 read-back mismatches" in text
    fs = Flowsheet.from_json(str(out / "case.json"))
    assert fs.streams["1"].T_C == 25.0 and fs.components == ["Ethanol", "Water"]   # values came from the H&MB


def test_pid_reconcile_error_blocks_exit_6(out, capsys, monkeypatch):
    ghost = Stream(id="9", src="E-100", dst="GHOST", kind="intermediate")
    monkeypatch.setattr(pid_extract, "extract", lambda p: topology(ghost, flagged=False))
    rc = run(out, "--pid", "d.png")
    text = capsys.readouterr().out
    assert rc == 6
    assert "reconcile: [ERROR] 9: references unknown unit 'GHOST'" in text
    assert "BLOCKED: reconciliation errors in P&ID topology; see " + str(out / "case.json") in text


def test_pid_reconcile_error_accepted_continues_past_gate(out, capsys, monkeypatch):
    ghost = Stream(id="9", src="E-100", dst="GHOST", kind="intermediate")
    monkeypatch.setattr(pid_extract, "extract", lambda p: topology(ghost, flagged=False))
    rc = run(out, "--pid", "d.png", "--accept-topology")
    text = capsys.readouterr().out
    assert "BLOCKED: reconciliation" not in text
    assert "merge: stream 9 on P&ID but not in H&MB" in text and rc != 6


def test_pid_autofix_actions_are_printed(out, capsys, monkeypatch):
    topo = topology(flagged=False)
    topo.streams["5"] = Stream(id="5", src="E-100", dst="E-100", kind="intermediate")   # self loop: auto-fixable
    monkeypatch.setattr(pid_extract, "extract", lambda p: topo)
    rc = run(out, "--pid", "d.png")
    text = capsys.readouterr().out
    assert "reconcile (auto-fix): removed self-loop stream 5 on E-100" in text
    assert rc == 0


def test_pid_truth_score_is_printed(out, capsys, monkeypatch):
    monkeypatch.setattr(pid_extract, "extract", lambda p: topology(flagged=False))
    truth = topology(flagged=False)
    truth.to_json(str(out / "truth.json"))
    assert run(out, "--pid", "d.png", "--truth", str(out / "truth.json")) == 0
    line = [l for l in capsys.readouterr().out.splitlines() if l.startswith("score:")]
    assert len(line) == 1 and "edges P/R/F1 1.00/1.00/1.00" in line[0]


def test_no_score_without_truth(out, capsys, monkeypatch):
    monkeypatch.setattr(pid_extract, "extract", lambda p: topology(flagged=False))
    run(out, "--pid", "d.png")
    assert "score:" not in capsys.readouterr().out


def test_pid_merge_notes_printed_with_prefix(out, capsys, monkeypatch):
    topo = topology(flagged=False)
    del topo.streams["2"]
    topo.relink()
    monkeypatch.setattr(pid_extract, "extract", lambda p: topo)
    run(out, "--pid", "d.png")
    assert "merge: stream 2 in H&MB but not on P&ID" in capsys.readouterr().out


# ---- exports ----------------------------------------------------------------------------------------------
def test_dexpi_export_option(out, capsys):
    p = out / "o.xml"
    assert run(out, "--dexpi", str(p)) == 0
    assert f"wrote {p}" in capsys.readouterr().out
    assert dexpi_export.load(str(p)).units.keys() == {"MX-100", "E-100"}


def test_dexpi_process_option_splits_dir_and_file(out, capsys, monkeypatch):
    from hysys_bridge import dexpi_process
    calls = []
    monkeypatch.setattr(dexpi_process, "export_json", lambda fs, d, f: calls.append((d, f)))
    assert run(out, "--dexpi-process", str(out / "sub" / "p.json")) == 0
    assert calls == [(str(out / "sub"), "p.json")]
    assert f"wrote {out / 'sub' / 'p.json'}" in capsys.readouterr().out


def test_no_exports_by_default(out, capsys, monkeypatch):
    monkeypatch.setattr(dexpi_export, "export", lambda *a: (_ for _ in ()).throw(AssertionError("exported")))
    assert run(out) == 0
    assert "wrote /" not in capsys.readouterr().out.replace("wrote 12", "")


def test_normalize_log_is_printed(out, capsys):
    f = out / "two.csv"
    f.write_text("Stream No.,1,2,3\nFrom,-,-,P-1\nTo,P-1,P-1,-\nTemperature (C),25,25,25\nPressure (kPa),500,500,500\n"
                 "Mass flow (kg/h),100,100,200\nComposition (mol%)\nA,100,100,100\n")
    assert cli.main([str(f), "--mock", "--out", str(out / "c.json"), "--audit", str(out / "a.csv")]) == 0
    assert "normalize: inserted mixer MX-P-1 ahead of P-1 (merged ['1', '2'])" in capsys.readouterr().out


def test_argparse_requires_input():
    with pytest.raises(SystemExit) as e:
        cli.main([])
    assert e.value.code == 2


def test_module_main_guard(out, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["hysys_bridge.cli", SAMPLE, "--mock", "--out", str(out / "c.json"), "--audit", str(out / "a.csv")])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(SystemExit) as e:
            runpy.run_module("hysys_bridge.cli", run_name="__main__")
    assert e.value.code == 0
