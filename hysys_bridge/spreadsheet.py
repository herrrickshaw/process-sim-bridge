"""Spreadsheet-based HYSYS link: write numbers into a spreadsheet operation, let HYSYS's own links move them.

Why: the direct COM writer (backend.HysysCOM) needs stream/operation creation calls and SetValue unit strings
that no open-source wrapper I read confirms. The spreadsheet route only needs what edgarsmdn/Aspen_HYSYS_Python
(MIT) demonstrates: Operations.Item(sheet).Cell(col, row).CellValue read/write and Solver.CanSolve / IsSolving.

CONTRACT (you build this once inside HYSYS; `spreadsheet_layout` generates the row list):
  * The HYSYS flowsheet (streams, unit operations, fluid package) already exists - this link never creates any.
  * Spreadsheet IN  (default name HMB_IN):  column 0 = label (key), column 1 = value. Each value cell is
    EXPORTED (Spreadsheet tab -> Connections / Exportable) to the stream variable named by the row.
  * Spreadsheet OUT (default HMB_OUT): same rows, column 1 IMPORTS the calculated stream variable.
  * Cell values are in the unit set you declare in `units` (default degC, kPa absolute, kg/h, kgmole/h, m3/h, mole
    fractions); set the same units on the imported/exported variables inside the spreadsheet or the numbers lie.
After solving, verify_propagation() compares what was written with what HYSYS reports on the OUT sheet, which
catches an unlinked cell, a wrong unit set or a wrong variable. Cell(col,row) indices are 0-based, as in the wrapper.

UNTESTED against a real HYSYS (no licence here). Tested: layout, unit conversion, read-back and propagation logic
against MockSheetCase, which imitates the contract (IN -> OUT copy on solve), including a seeded unit-mismatch.
"""
from __future__ import annotations
import csv, io, time
from dataclasses import dataclass, field
from .ir import Flowsheet
from . import hysys_writer

# sheet unit -> function canonical->sheet, and back.  Canonical: degC, kPa (absolute), kg/h, kmol/h, m3/h, fractions.
_LIN = lambda f: (lambda v: v * f, lambda v: v / f)
CONV = {
    "T": {"C": (lambda v: v, lambda v: v), "K": (lambda v: v + 273.15, lambda v: v - 273.15)},
    "P": {"kPa": _LIN(1.0), "bar": _LIN(0.01), "Pa": _LIN(1000.0), "MPa": _LIN(0.001)},
    "mass": {"kg/h": _LIN(1.0), "kg/s": _LIN(1 / 3600), "t/h": _LIN(0.001)},
    "mol": {"kgmole/h": _LIN(1.0), "kgmole/s": _LIN(1 / 3600)},
    "vol": {"m3/h": _LIN(1.0), "m3/s": _LIN(1 / 3600)},
    "vf": {"-": _LIN(1.0)}, "x": {"-": _LIN(1.0)},
}
DEFAULT_UNITS = {"T": "C", "P": "kPa", "mass": "kg/h", "mol": "kgmole/h", "vol": "m3/h", "vf": "-", "x": "-"}
OUT_PROPS = ("T", "P", "mass", "mol", "vol", "vf")
IN_COL = 1


def _kind(prop: str) -> str: return "x" if prop.startswith("x[") else prop


def to_sheet(prop: str, value: float, units: dict) -> float: return CONV[_kind(prop)][units[_kind(prop)]][0](value)
def from_sheet(prop: str, value: float, units: dict) -> float: return CONV[_kind(prop)][units[_kind(prop)]][1](value)


@dataclass
class Item:
    key: str; stream: str; prop: str; unit: str; row: int


@dataclass
class Layout:
    units: dict
    inputs: list[Item] = field(default_factory=list)
    outputs: list[Item] = field(default_factory=list)

    def csv(self) -> str:
        buf = io.StringIO(); w = csv.writer(buf)
        w.writerow(["sheet", "row", "label", "unit", "hysys_link"])
        for sheet, items, verb in (("IN", self.inputs, "export to"), ("OUT", self.outputs, "import from")):
            for i in items:
                w.writerow([sheet, i.row, i.key, i.unit, f"{verb} stream '{i.stream}' {i.prop}"])
        return buf.getvalue()


def make_units(units: dict | None) -> dict:
    u = {**DEFAULT_UNITS, **(units or {})}
    for k, v in u.items():
        if k not in CONV or v not in CONV[k]: raise ValueError(f"unit {v!r} not supported for {k}; options {sorted(CONV.get(k, {}))}")
    return u


def build_layout(fs: Flowsheet, units: dict | None = None) -> Layout:
    u = make_units(units); lay = Layout(u)
    def add(items, stream, prop):
        items.append(Item(f"{stream}|{prop}", stream, prop, u[_kind(prop)], len(items)))
    for stream, prop, _ in hysys_writer.plan_specs(fs): add(lay.inputs, stream, prop)
    for s in fs.streams.values():
        if s.kind == "feed" and s.composition:
            if s.composition_basis != "mole": raise ValueError(f"stream {s.id}: mass-basis composition; convert to mole fractions first")
            for c in fs.components: add(lay.inputs, s.id, f"x[{c}]")
    for s in fs.streams.values():
        for p in OUT_PROPS: add(lay.outputs, s.id, p)
        for c in fs.components: add(lay.outputs, s.id, f"x[{c}]")
    return lay


class SpreadsheetBackend:
    """Same interface as backend.Backend, but every value goes through spreadsheet cells.
    in_sheet/out_sheet need .Cell(col,row).CellValue; solver needs CanSolve and IsSolving."""

    def __init__(self, layout: Layout, in_sheet, out_sheet, solver, timeout_s: float = 120.0):
        self.layout, self.inp, self.out, self.solver, self.timeout_s = layout, in_sheet, out_sheet, solver, timeout_s
        self._in = {(i.stream, i.prop): i for i in layout.inputs}
        self._out = {(i.stream, i.prop): i for i in layout.outputs}

    # the flowsheet is built by the engineer in HYSYS: nothing to create
    def new_case(self, name, package, components): self.components = list(components)
    def add_stream(self, sid): pass
    def add_unit(self, uid, utype): pass
    def connect(self, uid, inlets, outlets): pass

    def set(self, sid, prop, value):
        it = self._in.get((sid, prop))
        if it is None: raise KeyError(f"{sid}|{prop} is not in the IN layout; regenerate the layout from this flowsheet")
        self.inp.Cell(IN_COL, it.row).CellValue = to_sheet(prop, value, self.layout.units)

    def set_comp(self, sid, x, basis):
        if basis != "mole": raise ValueError("spreadsheet link carries mole fractions only")
        for c, v in x.items(): self.set(sid, f"x[{c}]", v)

    def get(self, sid, prop):                                   # read-back of what was written (IN sheet)
        it = self._in.get((sid, prop))
        if it is None: return self.get_calc(sid, prop)
        raw = self.inp.Cell(IN_COL, it.row).CellValue
        return None if raw is None else from_sheet(prop, raw, self.layout.units)

    def get_calc(self, sid, prop):                              # what HYSYS calculated (OUT sheet)
        it = self._out.get((sid, prop))
        if it is None: return None
        raw = self.out.Cell(IN_COL, it.row).CellValue
        return None if raw is None else from_sheet(prop, raw, self.layout.units)

    def get_comp(self, sid):                                    # read-back of the written fractions (IN sheet)
        return {c: v for c in self.components if (sid, f"x[{c}]") in self._in and (v := self.get(sid, f"x[{c}]")) is not None}

    def get_comp_calc(self, sid):                               # calculated fractions (OUT sheet)
        return {c: v for c in self.components if (v := self.get_calc(sid, f"x[{c}]")) is not None}

    def solve(self):
        self.solver.CanSolve = True
        t0 = time.time()
        while self.solver.IsSolving:
            if time.time() - t0 > self.timeout_s: return False
            time.sleep(0.05)
        return True


@dataclass
class Prop:
    stream: str; prop: str; written: float; calculated: float | None; ok: bool

    def __str__(self): return f"{self.stream}|{self.prop}: wrote {self.written:.6g}, HYSYS reports {self.calculated}"


def verify_propagation(fs: Flowsheet, be: SpreadsheetBackend, rel_tol: float = 1e-6) -> list[Prop]:
    """After solve: every written spec must come back unchanged on the OUT sheet."""
    out = []
    written = {(s, p): v for s, p, v in hysys_writer.plan_specs(fs)}
    for s in fs.streams.values():
        if s.kind == "feed" and s.composition:
            for c in fs.components: written[(s.id, f"x[{c}]")] = s.composition.get(c, 0.0)
    for (sid, prop), v in written.items():
        got = be.get_calc(sid, prop)
        out.append(Prop(sid, prop, v, got, got is not None and abs(got - v) <= rel_tol * max(abs(v), 1.0) + 1e-9))
    return out


# ---- mock that imitates the contract (for rehearsal and tests) ----------------------------------------------
class _Cell:
    def __init__(self): self.CellValue = None


class MockSheet:
    def __init__(self): self._c: dict[tuple[int, int], _Cell] = {}
    def Cell(self, col, row): return self._c.setdefault((col, row), _Cell())


class MockSolver:
    def __init__(self, on_solve): self._can, self.IsSolving, self._on = False, False, on_solve
    @property
    def CanSolve(self): return self._can
    @CanSolve.setter
    def CanSolve(self, v):
        self._can = v
        if v: self._on()


class MockSheetCase:
    """IN cells -> (link) -> OUT cells on solve. `unit_bug` multiplies one prop to imitate a wrong unit set;
    `unlinked` drops rows to imitate an export that was never set up."""
    def __init__(self, layout: Layout, unit_bug: dict | None = None, unlinked: set | None = None):
        self.layout, self.inp, self.out = layout, MockSheet(), MockSheet()
        self.unit_bug, self.unlinked = unit_bug or {}, unlinked or set()
        self.solver = MockSolver(self._solve)

    def _solve(self):
        out_rows = {(i.stream, i.prop): i.row for i in self.layout.outputs}
        for i in self.layout.inputs:
            if (i.stream, i.prop) in self.unlinked: continue
            v = self.inp.Cell(IN_COL, i.row).CellValue
            if v is None: continue
            self.out.Cell(IN_COL, out_rows[(i.stream, i.prop)]).CellValue = v * self.unit_bug.get(i.prop, 1.0)

    def backend(self) -> SpreadsheetBackend:
        return SpreadsheetBackend(self.layout, self.inp, self.out, self.solver)


class HysysSheetCase:                                                                    # pragma: no cover
    """Live: open a case (or use the active one) and fetch the two spreadsheets as the wrapper does."""
    def __init__(self, layout: Layout, in_sheet="HMB_IN", out_sheet="HMB_OUT", open_path: str | None = None,
                 use_active: bool = False, visible: bool = False):
        import sys
        if sys.platform != "win32": raise RuntimeError("needs Windows + a licensed Aspen HYSYS install")
        import win32com.client
        app = win32com.client.Dispatch("HYSYS.Application"); app.Visible = visible
        if use_active: case = app.ActiveDocument
        elif open_path: case = app.SimulationCases.Open(open_path)
        else: raise ValueError("pass open_path or use_active")
        self.layout, self.case = layout, case
        self.inp = case.Flowsheet.Operations.Item(in_sheet); self.out = case.Flowsheet.Operations.Item(out_sheet)
        self.solver = case.Solver

    def backend(self) -> SpreadsheetBackend:
        return SpreadsheetBackend(self.layout, self.inp, self.out, self.solver)
