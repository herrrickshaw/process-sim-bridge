"""Heat & Mass Balance table -> ir.Flowsheet.

Expected layout (the usual one): ONE COLUMN PER STREAM, one row per property.
    Stream No.        | 1      | 2      | 3
    From              | -      | V-100  | E-101
    To                | V-100  | E-101  | -
    Temperature (°C)  | 25     | 40     | 80
    Pressure (barg)   | 2.0    | 1.5    | 1.0
    Mass flow (kg/h)  | 1000   | 1000   | 900
    Composition (mol%)
    Methane           | 90     | 90     | 85
    ...
Rows are located by label aliases; every extracted number keeps its source
cell for the audit trail. Nothing is guessed: unknown units raise.
"""
from __future__ import annotations
import csv, re
from .ir import Flowsheet, Stream, Unit
from . import units as U

NUM = re.compile(r"^\s*[<>~≈]?\s*(-?\d[\d,]*\.?\d*(?:[eE][-+]?\d+)?)\s*$")
BLANK = {"", "-", "—", "–", "n/a", "na", "nil", "none"}

ALIASES = {
    "T": ("temperature", "temp"),
    "P": ("pressure",),
    "mass": ("mass flow", "massflow", "mass flowrate", "total mass flow"),
    "mol": ("molar flow", "molarflow", "mole flow", "total molar flow"),
    "vol": ("volume flow", "vol flow", "volumetric flow", "actual volume flow"),
    "vf": ("vapour fraction", "vapor fraction", "vapour frac", "vapor frac"),
    "H": ("enthalpy", "heat flow"),
    "from": ("from",), "to": ("to",),
    "id": ("stream no", "stream number", "stream id", "stream", "stream name"),
}
SECTION = re.compile(r"composition\s*\((mol|mole|mass|wt|weight)\s*(%|fraction|frac)?\)|"
                     r"(mole|mol|mass|weight)\s*(%|fraction)", re.I)


def parse_num(cell: str):
    c = (cell or "").strip()
    if c.lower() in BLANK:
        return None
    m = NUM.match(c)
    if not m:
        raise ValueError(f"unparseable numeric cell {cell!r}")
    return float(m.group(1).replace(",", ""))


def _label_unit(label: str):
    m = re.search(r"\(([^)]+)\)", label)
    base = re.sub(r"\s*\([^)]*\)", "", label).strip().lower()
    return base, (m.group(1).strip() if m else None)


def _role(base: str):
    for role, names in ALIASES.items():
        if any(base == n or base.startswith(n) for n in names):
            return role
    return None


def from_rows(rows: list[list[str]], name="hmb", origin="table", row0=1) -> Flowsheet:
    rows = [[(c or "").strip() for c in r] for r in rows if any((c or "").strip() for c in r)]
    hdr_i = next((i for i, r in enumerate(rows) if _role(_label_unit(r[0])[0]) == "id"), None)
    if hdr_i is None:
        raise ValueError("no 'Stream No.' header row found")
    ids = rows[hdr_i][1:]
    if len(set(ids)) != len(ids) or any(not i for i in ids):
        raise ValueError(f"duplicate/blank stream ids: {ids}")
    fs = Flowsheet(name=name)
    st = {i: Stream(id=i) for i in ids}
    comp_unit = None                       # active composition section: 'mol%'|'mass%'|...
    for ri, r in enumerate(rows[hdr_i + 1:], start=hdr_i + 1):
        label, vals = r[0], r[1:]
        if all(v.lower() in BLANK for v in vals):         # section header rows may be short
            vals = vals + [""] * (len(ids) - len(vals))
        if len(vals) != len(ids):
            raise ValueError(f"row {label!r}: {len(vals)} cells for {len(ids)} streams")
        sec = SECTION.search(label)
        if sec and all(v.strip().lower() in BLANK for v in vals):
            txt = sec.group(0).lower()
            comp_unit = ("mass" if re.search(r"mass|wt|weight", txt) else "mole",
                         100.0 if "%" in txt else 1.0)
            continue
        base, unit = _label_unit(label)
        role = _role(base)
        for sid, cell in zip(ids, vals):
            s = st[sid]
            where = f"{origin} r{row0 + ri} '{label}' col '{sid}'"
            if role in ("from", "to"):
                v = None if cell.lower() in BLANK else cell
                setattr(s, "src" if role == "from" else "dst", v)
                continue
            if role is None:
                if comp_unit is None:
                    continue                      # unrelated row (notes etc.)
                v = parse_num(cell)
                if v is None: continue
                s.composition[label] = v / comp_unit[1]
                s.composition_basis = comp_unit[0]
                s.source[f"x[{label}]"] = where
                continue
            v = parse_num(cell)
            if v is None: continue
            comp_unit = None            # a property row ends any composition section
            if role == "T":   s.T_C = U.to_celsius(v, unit or "C")
            elif role == "P":
                if not unit: raise ValueError(f"{where}: pressure needs an explicit unit (g vs a)")
                s.P_kPa = U.to_kpa_abs(v, unit)
            elif role == "mass": s.mass_flow_kg_h = U.to_kg_h(v, unit or "kg/h")
            elif role == "mol":  s.molar_flow_kmol_h = U.to_kmol_h(v, unit or "kmol/h")
            elif role == "vol":  s.vol_flow_m3_h = U.to_m3_h(v, unit or "m3/h")
            elif role == "vf":   s.checks["vapour_fraction"] = v
            elif role == "H":    s.checks["enthalpy_kJ_h"] = U.to_kj_h(v, unit or "kJ/h")
            s.source[role] = where
            s.confidence[role] = 1.0
    for s in st.values():
        s.kind = "feed" if s.src is None else ("product" if s.dst is None else "intermediate")
    fs.streams = st
    fs.components = sorted({c for s in st.values() for c in s.composition})
    for s in st.values():
        for u in (s.src, s.dst):
            if u and u not in fs.units:
                fs.units[u] = Unit(id=u, type=guess_unit_type(u))
    fs.relink()
    return fs


def guess_unit_type(tag: str) -> str:
    """ISA-ish tag prefix -> HYSYS-ish type. Unknown => 'unknown' (flagged, never guessed)."""
    p = re.match(r"([A-Za-z]+)", tag)
    return {"P": "pump", "E": "heater", "H": "heater", "C": "cooler", "V": "separator",
            "D": "separator", "K": "compressor", "T": "column", "MX": "mixer", "SP": "splitter",
            "FV": "valve", "PV": "valve", "LV": "valve", "R": "reactor"}.get(
        p.group(1).upper() if p else "", "unknown")


def from_csv(path: str, **kw) -> Flowsheet:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return from_rows(list(csv.reader(f)), origin=path, **kw)


def from_pdf(path: str, page: int | None = None, **kw) -> Flowsheet:
    """Vector PDF only. Scanned PDFs need OCR + mandatory human review (not done here)."""
    try:
        import pdfplumber
    except ImportError as e:                                  # pragma: no cover
        raise SystemExit("pip install pdfplumber") from e
    rows: list[list[str]] = []
    with pdfplumber.open(path) as pdf:
        pages = [pdf.pages[page - 1]] if page else pdf.pages
        for pg in pages:
            if not pg.extract_text():
                raise ValueError(f"{path} p{pg.page_number}: no text layer (scanned?) - OCR + review required")
            for t in pg.extract_tables():
                rows.extend(t)
    return from_rows(rows, origin=path, **kw)
