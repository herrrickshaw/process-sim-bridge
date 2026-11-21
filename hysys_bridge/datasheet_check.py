"""Data-sheet attribute mismatch check: the same equipment or stream, described by several documents (a P&ID topology, an H&MB, one or more vendor or EPC data sheets),
is compared attribute by attribute. It reports what disagrees; it never decides which document is right and never changes any of them.

Sources. A flowsheet (P&ID or H&MB) gives, per stream, T, P, mass flow, molar flow and volume flow, and per unit, its type and numeric params.
A data sheet is a table of rows item, attribute, value, unit (optional source note): CSV with those headers, or a list of such dicts.
Attributes with a known quantity are converted to one basis before comparison (temperature C, pressure kPa absolute, mass flow kg/h, molar flow kmol/h, volume flow m3/h,
duty kJ/h); a unit the converter does not know, or a pressure whose gauge or absolute basis is not stated, is reported as UNIT_UNREADABLE and left out (never guessed).
Other numeric attributes are compared only when both rows carry the same unit string; otherwise UNITS_NOT_COMPARABLE. Text attributes (type, service, material) are compared
case-insensitively with spaces and hyphens ignored.

Tolerances are the caller's: `rel_tol` (default 0.005, a tool default) and `temp_tol_C` (default 0.5 C, a tool default), both echoed in the result. Finding codes:
VALUE_MISMATCH, TYPE_MISMATCH, TEXT_MISMATCH, DUPLICATE_CONFLICT (one source gives two different values for the same item and attribute), MISSING_IN_SOURCE (an item or attribute
that some sources carry and others do not; informational), OPERATING_EXCEEDS_DESIGN (operating pressure or temperature above design in the same item, any sources), UNIT_UNREADABLE,
UNITS_NOT_COMPARABLE. Design margins and which value to trust are engineering decisions and are not made here."""
from __future__ import annotations
import csv, io, math
from . import units as U

QUANTITY = {  # attribute -> (quantity, converter to the canonical unit)
    "T": ("temperature_C", U.to_celsius), "operating_temperature": ("temperature_C", U.to_celsius), "design_temperature": ("temperature_C", U.to_celsius),
    "P": ("pressure_kPa", U.to_kpa_abs), "operating_pressure": ("pressure_kPa", U.to_kpa_abs), "design_pressure": ("pressure_kPa", U.to_kpa_abs),
    "mass_flow": ("mass_flow_kg_h", U.to_kg_h), "molar_flow": ("molar_flow_kmol_h", U.to_kmol_h), "vol_flow": ("vol_flow_m3_h", U.to_m3_h), "duty": ("duty_kJ_h", U.to_kj_h),
}
CANON_UNIT = {"temperature_C": "C", "pressure_kPa": "kPa abs", "mass_flow_kg_h": "kg/h", "molar_flow_kmol_h": "kmol/h", "vol_flow_m3_h": "m3/h", "duty_kJ_h": "kJ/h"}
AMBIGUOUS_P = {"bar", "kpa", "mpa", "pa", "psi", "kg/cm2"}   # no stated gauge or absolute basis
TEXT = {"type", "service", "material", "fluid", "model", "manufacturer"}
PAIRS = [("operating_pressure", "design_pressure"), ("operating_temperature", "design_temperature")]
STREAM_FIELDS = {"T_C": ("T", 1.0), "P_kPa": ("P", 1.0), "mass_flow_kg_h": ("mass_flow", 1.0), "molar_flow_kmol_h": ("molar_flow", 1.0), "vol_flow_m3_h": ("vol_flow", 1.0)}
STREAM_UNIT = {"T": "C", "P": "kPaa", "mass_flow": "kg/h", "molar_flow": "kmol/h", "vol_flow": "m3/h"}   # flowsheet P_kPa is absolute by the IR's definition


def _txt(v) -> str: return "".join(ch for ch in str(v).lower() if ch.isalnum())


def rows_from_flowsheet(name: str, fs) -> list[dict]:
    rows = []
    for sid, s in fs.streams.items():
        for f, (attr, _) in STREAM_FIELDS.items():
            v = getattr(s, f)
            if v is not None: rows.append({"source": name, "item": sid, "attribute": attr, "value": v, "unit": STREAM_UNIT[attr]})
    for uid, u in fs.units.items():
        rows.append({"source": name, "item": uid, "attribute": "type", "value": u.type, "unit": ""})
        for k, v in u.params.items(): rows.append({"source": name, "item": uid, "attribute": k, "value": v, "unit": ""})
    return rows


def rows_from_datasheet(name: str, data) -> list[dict]:
    """`data` is CSV text or a list of dicts with item, attribute, value, unit (and optionally note)."""
    recs = list(csv.DictReader(io.StringIO(data))) if isinstance(data, str) else list(data)
    out = []
    for i, r in enumerate(recs, 1):
        r = {str(k).strip().lower(): v for k, v in r.items()}
        miss = [k for k in ("item", "attribute", "value") if not str(r.get(k, "")).strip()]
        if miss: raise ValueError(f"{name} row {i}: missing {', '.join(miss)}")
        out.append({"source": name, "item": str(r["item"]).strip(), "attribute": str(r["attribute"]).strip(), "value": str(r["value"]).strip(), "unit": str(r.get("unit") or "").strip(), "note": r.get("note") or r.get("source") or ""})
    return out


def _canon(row):
    """-> (kind, value, unit, problem): kind 'num' or 'text'; numeric values converted when the attribute has a known quantity."""
    a, v, u = row["attribute"], row["value"], row["unit"]
    if a in TEXT or a == "type":
        return "text", _txt(v), "", None
    try: x = float(v)
    except (TypeError, ValueError): return "text", _txt(v), "", None
    if not math.isfinite(x): return "num", None, u, f"value {v!r} is not a finite number"
    if a in QUANTITY:
        q, conv = QUANTITY[a]
        if not u: return "num", None, u, f"{a} needs a unit"
        if q == "pressure_kPa" and U._norm(u) in AMBIGUOUS_P: return "num", None, u, f"pressure unit {u!r}: gauge vs abs must be explicit (use barg/bara, kPag/kPaa, psig/psia)"
        try: return "num", conv(x, u), CANON_UNIT[q], None
        except ValueError as e: return "num", None, u, str(e)
    return "num", x, u, None


def check(rows: list[dict], rel_tol: float = 0.005, temp_tol_C: float = 0.5) -> dict:
    if rel_tol < 0 or temp_tol_C < 0: raise ValueError("tolerances cannot be negative")
    sources = sorted({r["source"] for r in rows}); findings = []
    def add(code, item, attr, detail, vals=()): findings.append({"code": code, "item": item, "attribute": attr, "detail": detail, "values": list(vals)})
    cell: dict[tuple, dict[str, list]] = {}
    for r in rows:
        kind, v, u, prob = _canon(r)
        if prob: add("UNIT_UNREADABLE", r["item"], r["attribute"], f"{r['source']}: {prob} (value {r['value']!r} {r['unit']!r}); left out of the comparison"); continue
        cell.setdefault((r["item"], r["attribute"]), {}).setdefault(r["source"], []).append((kind, v, u, r))
    for (item, attr), by_src in sorted(cell.items()):
        vals = []
        for src, lst in sorted(by_src.items()):
            first = lst[0]
            for other in lst[1:]:
                if _differs(first, other, attr, rel_tol, temp_tol_C): add("DUPLICATE_CONFLICT", item, attr, f"{src} gives different values for the same item and attribute", [_show(src, x) for x in lst]); break
            vals.append((src, first))
        if len(vals) < len(sources): add("MISSING_IN_SOURCE", item, attr, "not given by " + ", ".join(s for s in sources if s not in by_src), [_show(s, x) for s, x in vals])
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                (s1, a1), (s2, a2) = vals[i], vals[j]
                if a1[0] != a2[0]: add("TEXT_MISMATCH" if attr in TEXT or attr == "type" else "VALUE_MISMATCH", item, attr, f"{s1} gives a {a1[0]} and {s2} a {a2[0]}", [_show(s1, a1), _show(s2, a2)]); continue
                if a1[0] == "text":
                    if a1[1] != a2[1]: add("TYPE_MISMATCH" if attr == "type" else "TEXT_MISMATCH", item, attr, f"{s1} and {s2} disagree", [_show(s1, a1), _show(s2, a2)])
                elif a1[2] != a2[2]: add("UNITS_NOT_COMPARABLE", item, attr, f"{s1} uses {a1[2] or '(none)'} and {s2} uses {a2[2] or '(none)'}; not converted", [_show(s1, a1), _show(s2, a2)])
                elif _differs(a1, a2, attr, rel_tol, temp_tol_C):
                    d = abs(a1[1] - a2[1]); rel = d / max(abs(a1[1]), abs(a2[1])) if max(abs(a1[1]), abs(a2[1])) else 0.0
                    add("VALUE_MISMATCH", item, attr, f"{s1} and {s2} differ by {d:.6g} {a1[2]}" + ("" if a1[2] == "C" else f" ({rel * 100:.3g}%)"), [_show(s1, a1), _show(s2, a2)])
    for op, dg in PAIRS:
        for item in sorted({i for (i, a) in cell if a == op} & {i for (i, a) in cell if a == dg}):
            for so, (_, vo, uo, ro) in [(s, l[0]) for s, l in cell[(item, op)].items()]:
                for sd, (_, vd, ud, rd) in [(s, l[0]) for s, l in cell[(item, dg)].items()]:
                    if isinstance(vo, float) and isinstance(vd, float) and vo > vd: add("OPERATING_EXCEEDS_DESIGN", item, op, f"{op} {vo:.6g} {uo} ({so}) is above {dg} {vd:.6g} {ud} ({sd})", [{"source": so, "value": vo, "unit": uo}, {"source": sd, "value": vd, "unit": ud}])
    counts: dict[str, int] = {}
    for f in findings: counts[f["code"]] = counts.get(f["code"], 0) + 1
    return {"sources": sources, "rows": len(rows), "tolerances": {"rel_tol": rel_tol, "temp_tol_C": temp_tol_C, "basis": "tool defaults unless the caller set them"},
            "findings": findings, "counts": counts, "agree": not any(f["code"] != "MISSING_IN_SOURCE" for f in findings),
            "note": "reports disagreement only; which document is right, and any design margin, are engineering decisions"}


def _show(src, x): return {"source": src, "value": x[1], "unit": x[2], "raw": f"{x[3]['value']} {x[3]['unit']}".strip()}


def _differs(a, b, attr, rel_tol, temp_tol_C) -> bool:
    if a[0] != b[0]: return True
    if a[0] == "text": return a[1] != b[1]
    if a[2] != b[2]: return False                    # not comparable: reported separately
    d = abs(a[1] - b[1])
    if a[2] == "C": return d > temp_tol_C
    m = max(abs(a[1]), abs(b[1]))
    return d > rel_tol * m if m else False


def _read_sheet(path: str) -> str:
    from .mcp_server import _read_path
    p = _read_path(path, {".csv"})
    with open(p, encoding="utf-8-sig") as f: return f.read()


def t_datasheet_check(a):
    from .mcp_server import _fs
    rows = []
    for key in ("pid", "hmb"):
        if a.get(key): rows += rows_from_flowsheet(key, _fs(a[key]))
    sheets = a.get("sheets") or []
    if not isinstance(sheets, list): raise ValueError("sheets must be a list of {name, path} (a CSV with item, attribute, value, unit columns)")
    for s in sheets:
        if not s.get("name") or not s.get("path"): raise ValueError("each sheet needs a name and a path")
        rows += rows_from_datasheet(s["name"], _read_sheet(s["path"]))
    names = [s.get("name") for s in sheets] + [k for k in ("pid", "hmb") if a.get(k)]
    if len(set(names)) != len(names): raise ValueError("source names must be distinct (pid and hmb are reserved)")
    if len({r["source"] for r in rows}) < 2: raise ValueError("give at least two sources (pid, hmb, or sheets) to compare")
    return check(rows, float(a.get("rel_tol", 0.005)), float(a.get("temp_tol_C", 0.5)))


def _s(props, req): return {"type": "object", "properties": props, "required": req, "additionalProperties": False}
TOOLS = {"datasheet_check": (t_datasheet_check,
         "Compare the same items across a P&ID session, an H&MB session and vendor/EPC data-sheet CSVs (item, attribute, value, unit columns): value, type and text mismatches, conflicting duplicates, "
         "operating above design, unreadable or non-comparable units, items missing from a source. Reports only; never changes a document or picks the right one. Tolerances are echoed.",
         _s({"pid": {"type": "string", "description": "session name of the P&ID topology"}, "hmb": {"type": "string", "description": "session name of the H&MB"},
             "sheets": {"type": "array", "items": _s({"name": {"type": "string"}, "path": {"type": "string"}}, ["name", "path"])},
             "rel_tol": {"type": "number"}, "temp_tol_C": {"type": "number"}}, []))}


def main(argv=None) -> int:
    """python3 -m hysys_bridge.datasheet_check [--pid fs.json] [--hmb fs.json] [--sheet name=file.csv ...] [--rel-tol x] [--temp-tol-C x]"""
    import json, sys
    from .ir import Flowsheet
    argv = list(sys.argv[1:] if argv is None else argv); rows = []; rel, tt = 0.005, 0.5; i = 0
    while i < len(argv):
        k, v = argv[i], argv[i + 1] if i + 1 < len(argv) else None
        if v is None: print(f"{k} needs a value"); return 2
        if k in ("--pid", "--hmb"): rows += rows_from_flowsheet(k[2:], Flowsheet.from_json(v))
        elif k == "--sheet":
            name, _, path = v.partition("=")
            with open(path, encoding="utf-8-sig") as f: rows += rows_from_datasheet(name, f.read())
        elif k == "--rel-tol": rel = float(v)
        elif k == "--temp-tol-C": tt = float(v)
        else: print(f"unknown option {k}"); return 2
        i += 2
    if len({r["source"] for r in rows}) < 2: print("give at least two sources"); return 2
    out = check(rows, rel, tt); print(json.dumps(out, indent=2))
    return 0 if out["agree"] else 1


if __name__ == "__main__": raise SystemExit(main())
