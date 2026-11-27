"""HMB audit and report for bridge flowsheets, using `hmb_audit` / `hmb_report` from the process-safety-design-toolkit (MIT, separate repo).

    PROCESS_SAFETY_PATH=/path/to/process-safety-design-toolkit \
    python -m hysys_bridge.hmb_report_link design.csv --model results.csv --pid pid.xml --extra extra.json --out-dir out

design / model are HMB tables (CSV or vector PDF, read by `extract_hmb`); --pid is DEXPI-style XML (read by `dexpi_export.load`) or a
flowsheet JSON. The balance logic lives only in the toolkit; this file converts the data and never fills a gap:
  * mass flow is not derived from molar flow; a stream without it is "not checked"
  * absolute pressure becomes gauge with the standard atmosphere; HMB enthalpy flow becomes H_kW
  * unit duty, work, reactions, enthalpy basis and molar masses come only from `extra` (JSON keys: unit_data {tag: {duty_kW, work_kW,
    reactive, generation_kg_h}}, enthalpy_basis, molar_masses, line_map {stream: P&ID line}, audit {tolerances})
  * with a P&ID, each stream is matched to the P&ID connection with the same id (or the one named in line_map)
"""
from __future__ import annotations
import argparse, json, os, sys

from . import dexpi_export, extract_hmb
from .ir import Flowsheet
from .safety_link import _module
from .units import ATM_KPA

EXTRA_KEYS = {"unit_data", "enthalpy_basis", "molar_masses", "line_map", "audit"}
UNIT_KEYS = {"duty_kW", "work_kW", "reactive", "generation_kg_h"}


def _streams(fs: Flowsheet) -> list[dict]:
    out = []
    for s in fs.streams.values():
        h = s.checks.get("enthalpy_kJ_h")
        src = s.source.get("mass") or next(iter(s.source.values()), None)
        out.append({"id": s.id, "from": s.src, "to": s.dst, "T_C": s.T_C,
                    "P_kpag": None if s.P_kPa is None else s.P_kPa - ATM_KPA, "mass_kg_h": s.mass_flow_kg_h,
                    "H_kW": None if h is None else h / 3600.0, "components": dict(s.composition),
                    "component_basis": s.composition_basis if s.composition else None,
                    "source": src.split(" '")[0] if src else None})
    return out


def to_spec(design: Flowsheet, model: Flowsheet | None = None, pid: Flowsheet | None = None, extra: dict | None = None) -> dict:
    extra = extra or {}
    bad = sorted(set(extra) - EXTRA_KEYS)
    if bad: raise ValueError(f"unknown extra key(s) {bad}; allowed: {sorted(EXTRA_KEYS)}")
    data = extra.get("unit_data") or {}
    units = {u.id: {"tag": u.id, "type": u.type} for u in design.units.values()}
    for u in (pid.units.values() if pid else []):
        units.setdefault(u.id, {"tag": u.id, "type": u.type})
    for tag, d in data.items():
        if tag not in units: raise ValueError(f"unit_data names unknown unit {tag!r}")
        wrong = sorted(set(d) - UNIT_KEYS)
        if wrong: raise ValueError(f"unit_data[{tag!r}]: unknown key(s) {wrong}")
        units[tag].update(d)
    streams = _streams(design)
    lines, notes = [], []
    line_map = extra.get("line_map") or {}
    unknown = sorted(set(line_map) - set(design.streams))
    if unknown: raise ValueError(f"line_map names unknown stream(s) {unknown}")
    if pid:
        lines = [{"line_no": s.id, "from": s.src, "to": s.dst} for s in pid.streams.values()]
        for s in streams:
            s["line_no"] = line_map.get(s["id"], s["id"])
        notes.append("P&ID lines are the P&ID flowsheet's connections, matched to HMB streams by id or line_map")
        draft = [u.id for u in pid.units.values() if "needs-signoff" in u.flags]
        if draft: notes.append(f"P&ID topology is a DRAFT needing sign-off ({len(draft)} units): link results are provisional")
    spec = {"name": design.name, "units": list(units.values()), "streams": streams, "lines": lines}
    if model: spec["model_streams"] = _streams(model)
    for k in ("enthalpy_basis", "molar_masses", "audit"):
        if k in extra: spec[k] = extra[k]
    spec["_bridge_notes"] = notes
    return spec


def build(design: Flowsheet, model: Flowsheet | None, pid: Flowsheet | None, extra: dict | None, out_dir: str, overwrite: bool = False) -> dict:
    A, R = _module("hmb_audit"), _module("hmb_report")
    spec = to_spec(design, model, pid, extra)
    result = A.audit(spec)
    result["notes"] += spec["_bridge_notes"]
    os.makedirs(out_dir, exist_ok=True)
    prefix = os.path.join(os.path.abspath(out_dir), "hmb")
    clash = [p for p in (prefix + "_report.xlsx", prefix + "_report.html", prefix + "_findings.csv") if os.path.exists(p)]
    if clash and not overwrite: raise FileExistsError(f"{clash[0]} exists; pass overwrite=true to replace it")
    return {"verdict": result["verdict"], "counts": result["counts"], "findings": result["findings"][:100],
            "files": R.write(result, prefix), "notes": result["notes"], "limits": result["limits"]}


def _load(path: str) -> Flowsheet:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xml": return dexpi_export.load(path)
    if ext == ".json": return Flowsheet.from_json(path)
    return (extract_hmb.from_pdf if ext == ".pdf" else extract_hmb.from_csv)(path)


def t_hmb_report(a):
    from . import mcp_server as M
    extra = None
    if a.get("extra_path"):
        with open(M._read_path(a["extra_path"], {".json"}), encoding="utf-8") as f: extra = json.load(f)
    return build(M._fs(a["name"]), M._fs(a["model"]) if a.get("model") else None, M._fs(a["pid"]) if a.get("pid") else None,
                 extra, a["out_dir"], bool(a.get("overwrite")))


_S = {"type": "string"}
TOOLS = {"safety_hmb_report": (t_hmb_report,
    "Audit an HMB session: mass/component/energy closure, differences from a model-results session, links to a P&ID session; writes "
    "Excel, HTML and CSV. Missing data is 'not checked', never a pass. Needs PROCESS_SAFETY_PATH.",
    {"type": "object", "properties": {"name": _S, "model": _S, "pid": _S, "extra_path": _S, "out_dir": _S, "overwrite": {"type": "boolean"}},
     "required": ["name", "out_dir"], "additionalProperties": False})}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hysys_bridge.hmb_report_link")
    ap.add_argument("design"); ap.add_argument("--model"); ap.add_argument("--pid"); ap.add_argument("--extra")
    ap.add_argument("--out-dir", default="hmb_out"); ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args(argv)
    extra = None
    if a.extra:
        with open(a.extra, encoding="utf-8") as f: extra = json.load(f)
    r = build(_load(a.design), _load(a.model) if a.model else None, _load(a.pid) if a.pid else None, extra, a.out_dir, a.overwrite)
    print(json.dumps({k: r[k] for k in ("verdict", "counts", "files", "notes")}, indent=2))
    return {"pass": 0, "fail": 2, "not_checked": 3}[r["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
