"""Link to ppac-ready-reckoner-data (herrrickshaw/ppac-ready-reckoner-data, separate repo): India oil and gas statistics from PPAC's Ready Reckoner, 100 tables as CSV with an index.
Used as a reference to compare a model's figure (for example a refinery balance or utilities result) with a published one. The data folder is the operator-set env var
PPAC_DATA_PATH (the repo folder, or its `annual_fy2025-26_h1` subfolder); a tool argument can never supply it.

The repository says the figures are PPAC's own as extracted, with no cleaning, so cell values should be checked against the source PDF. Tables have multi-row headers, so
ppac_table returns the raw rows with their 0-based indices; ppac_compare takes a row label that must match exactly one row and a 0-based column, and the caller states the
unit (nothing is guessed). A cell that is not a plain number is refused.
"""
from __future__ import annotations
import csv, os, re

CAVEAT = "PPAC figures as extracted by the repository (no cleaning); check the cell against the source PDF before relying on it"


def _root() -> str:
    p = os.environ.get("PPAC_DATA_PATH")
    if not p: raise PermissionError("set PPAC_DATA_PATH to the ppac-ready-reckoner-data folder")
    p = os.path.abspath(os.path.expanduser(p))
    for cand in (p, os.path.join(p, "annual_fy2025-26_h1")):
        if os.path.isfile(os.path.join(cand, "index.csv")): return cand
    raise FileNotFoundError("no index.csv under PPAC_DATA_PATH")


def _index() -> list[dict]:
    with open(os.path.join(_root(), "index.csv"), newline="", encoding="utf-8") as f: return [r for r in csv.DictReader(f) if r["table_no"]]


def _entry(table_no: str) -> dict:
    hit = [r for r in _index() if r["table_no"] == str(table_no)]
    if not hit: raise KeyError(f"no table {table_no!r} in the index")
    return hit[0]


def _rows(table_no: str) -> tuple[dict, list[list[str]]]:
    e = _entry(table_no); path = os.path.realpath(os.path.join(_root(), e["csv_file"]))
    if not path.startswith(os.path.realpath(_root()) + os.sep): raise ValueError("table path escapes the data folder")
    with open(path, newline="", encoding="utf-8") as f: return e, list(csv.reader(f))


def number(cell: str) -> float:
    c = cell.strip().replace(",", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", c): raise ValueError(f"cell {cell!r} is not a plain number")
    return float(c)


def t_search(a):
    words = [w.lower() for w in str(a.get("query", "")).split() if w]
    if not words: raise ValueError("query is required")
    squash = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    hits = [r for r in _index() if all(squash(w) in squash(r["caption"]) for w in words)]
    return {"matches": [{"table_no": r["table_no"], "caption": r["caption"], "page": r["page"], "rows": r["rows"], "cols": r["cols"]} for r in hits[: int(a.get("limit", 20))]], "total_matches": len(hits), "caveat": CAVEAT}


def t_table(a):
    e, rows = _rows(a["table_no"]); lim = int(a.get("limit", 60))
    return {"table_no": e["table_no"], "caption": e["caption"], "page": e["page"], "n_rows": len(rows), "rows": [{"row": i, "cells": r} for i, r in enumerate(rows[:lim])], "truncated": len(rows) > lim,
            "note": "raw extracted rows; headers span several rows, so read the column index off them", "caveat": CAVEAT}


def t_compare(a):
    for k in ("table_no", "row_label", "col", "model_value", "unit_note"):
        if a.get(k) in (None, ""): raise ValueError(f"{k} is required")
    e, rows = _rows(a["table_no"]); lab = str(a["row_label"]).strip().lower()
    hit = [i for i, r in enumerate(rows) if any(c.strip().lower() == lab for c in r[:3])]
    if len(hit) != 1: raise ValueError(f"row_label {a['row_label']!r} matches {len(hit)} rows (exact match on the first three cells); use ppac_table to find the row")
    col = int(a["col"]); row = rows[hit[0]]
    if not 0 <= col < len(row): raise ValueError(f"col {col} is outside the row ({len(row)} cells)")
    ref = number(row[col]); mv = float(a["model_value"]); d = mv - ref
    return {"table_no": e["table_no"], "caption": e["caption"], "row": hit[0], "col": col, "published_cell": row[col], "published_value": ref, "model_value": mv, "unit_stated_by_caller": a["unit_note"],
            "difference": d, "difference_pct_of_published": (d / ref * 100.0) if ref else None, "caveat": CAVEAT, "note": "the caller states that the model value and the cell are in the same unit; the tool cannot check it"}


def _s(props, req): return {"type": "object", "properties": props, "required": req, "additionalProperties": False}
TOOLS = {
    "ppac_search": (t_search, "Search the PPAC Ready Reckoner table index (India oil and gas statistics) by caption words. Needs PPAC_DATA_PATH set by the operator.", _s({"query": {"type": "string"}, "limit": {"type": "integer"}}, ["query"])),
    "ppac_table": (t_table, "Read one PPAC table as raw rows with 0-based row indices (headers span several rows). Needs PPAC_DATA_PATH.", _s({"table_no": {"type": "string"}, "limit": {"type": "integer"}}, ["table_no"])),
    "ppac_compare": (t_compare, "Compare a model figure with one published PPAC cell: table, a row label matching exactly one row, a 0-based column, your value and the unit you state. Reports the difference; does not judge it. Needs PPAC_DATA_PATH.",
                     _s({"table_no": {"type": "string"}, "row_label": {"type": "string"}, "col": {"type": "integer"}, "model_value": {"type": "number"}, "unit_note": {"type": "string"}}, ["table_no", "row_label", "col", "model_value", "unit_note"])),
}
