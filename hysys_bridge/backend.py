"""HYSYS backends. One interface; COM (Windows+HYSYS) and Mock (any OS, for tests/dry runs).

!! HysysCOM is UNTESTED here (no HYSYS on this machine).
!! Cross-checked against two open-source HYSYS wrappers (read, not copied):
!!   edgarsmdn/Aspen_HYSYS_Python (MIT): Dispatch('HYSYS.Application'), SimulationCases.Open(path) or ActiveDocument,
!!     case.Flowsheet.MaterialStreams / EnergyStreams / Operations.Item(name), case.Solver.CanSolve (False while editing,
!!     True after) and Solver.IsSolving polled until False; interface units degC, kPa, kgmole/s, kJ/s.
!!   aspen-pysys (PyPI): HysysApp.dispatch(), open(path), get_flowsheet(), get_material_stream(name).
!! NOT confirmed by either: MaterialStreams.Add, Operations.Add type strings (TYPE_MAP), SetValue(value, unit) on
!! stream variables, ComponentMolarFraction.Values. Verify those once against your install before trusting a write.
"""
from __future__ import annotations
from typing import Protocol

# our property key -> (HYSYS stream attribute, HYSYS unit string)
PROPS = {"T": ("Temperature", "C"), "P": ("Pressure", "kPa"), "mass": ("MassFlow", "kg/h"),
         "mol": ("MolarFlow", "kgmole/h"), "vol": ("ActualVolumeFlow", "m3/h"),
         "vf": ("VapourFraction", ""), "H": ("MolarEnthalpy", "kJ/kgmole")}
TYPE_MAP = {"mixer": "mixerop", "splitter": "teeop", "pump": "pumpop", "heater": "heaterop",
            "cooler": "coolerop", "valve": "valveop", "compressor": "compressor",
            "separator": "vesselop"}


class Backend(Protocol):
    def new_case(self, name: str, package: str, components: list[str]) -> None: ...
    def add_stream(self, sid: str) -> None: ...
    def add_unit(self, uid: str, utype: str) -> None: ...
    def connect(self, uid: str, inlets: list[str], outlets: list[str]) -> None: ...
    def set(self, sid: str, prop: str, value: float) -> None: ...
    def set_comp(self, sid: str, x: dict[str, float], basis: str) -> None: ...
    def get(self, sid: str, prop: str) -> float | None: ...
    def get_comp(self, sid: str) -> dict[str, float]: ...
    def solve(self) -> bool: ...


class HysysCOM:                                              # pragma: no cover
    def __init__(self, visible=False, open_path: str | None = None, use_active: bool = False):
        import sys
        if sys.platform != "win32": raise RuntimeError("HysysCOM needs Windows + a licensed Aspen HYSYS install")
        import win32com.client                                # Windows only
        self.app = win32com.client.Dispatch("HYSYS.Application")
        self.app.Visible = visible
        self._open_path, self._use_active = open_path, use_active

    def new_case(self, name, package, components):
        if self._use_active:
            self.case = self.app.ActiveDocument               # never touches a case the user did not point us at
        elif self._open_path:
            self.case = self.app.SimulationCases.Open(self._open_path)
        else:
            self.case = self.app.SimulationCases.Add(name)    # unverified in the open-source wrappers
        fp = self.case.BasisManager.FluidPackages.Add("Basis-1")
        fp.PropertyPackageName = package
        for c in components:
            fp.Components.Add(c)               # raises if name not in HYSYS db -> loud failure
        self.comps = components
        self.fs = self.case.Flowsheet
        self.case.Solver.CanSolve = False      # build without recalculating each edit

    def add_stream(self, sid): self.fs.MaterialStreams.Add(sid)
    def add_unit(self, uid, utype): self.fs.Operations.Add(uid, TYPE_MAP[utype])

    def connect(self, uid, inlets, outlets):
        op = self.fs.Operations.Item(uid)
        for i in inlets: op.Feeds.Add(i)
        for o in outlets:
            (op.Products if hasattr(op, "Products") else op.Product).Add(o)

    def set(self, sid, prop, value):
        attr, unit = PROPS[prop]
        getattr(self.fs.MaterialStreams.Item(sid), attr).SetValue(value, unit)

    def set_comp(self, sid, x, basis):
        vec = tuple(x.get(c, 0.0) for c in self.comps)
        s = self.fs.MaterialStreams.Item(sid)
        (s.ComponentMassFraction if basis == "mass" else s.ComponentMolarFraction).Values = vec

    def get(self, sid, prop):
        attr, unit = PROPS[prop]
        o = getattr(self.fs.MaterialStreams.Item(sid), attr)
        try:
            return o.GetValue(unit) if unit else o.Value
        except Exception:
            return None                          # not yet calculated

    def get_comp(self, sid):
        vals = self.fs.MaterialStreams.Item(sid).ComponentMolarFraction.Values
        return dict(zip(self.comps, vals))

    def solve(self, timeout_s: float = 120.0):
        import time
        self.case.Solver.CanSolve = True
        t0 = time.time()
        while self.case.Solver.IsSolving:                     # polled, as in edgarsmdn/Aspen_HYSYS_Python
            if time.time() - t0 > timeout_s: return False
            time.sleep(0.05)
        return True


class MockHysys:
    """Stores what it is given; optional `corrupt` hook simulates a bad write for tests."""
    def __init__(self, corrupt=None, calc=None):
        self.vals: dict[tuple[str, str], float] = {}
        self.comp: dict[str, dict[str, float]] = {}
        self.streams, self.units, self.corrupt, self.calc = set(), {}, corrupt, calc or {}

    def new_case(self, name, package, components): self.components = components
    def add_stream(self, sid): self.streams.add(sid)
    def add_unit(self, uid, utype):
        if utype not in TYPE_MAP: raise KeyError(f"no HYSYS type for {utype}")
        self.units[uid] = ([], [])
    def connect(self, uid, i, o): self.units[uid] = (list(i), list(o))
    def set(self, sid, prop, value):
        self.vals[(sid, prop)] = self.corrupt(sid, prop, value) if self.corrupt else value
    def set_comp(self, sid, x, basis): self.comp[sid] = dict(x)
    def get(self, sid, prop): return self.vals.get((sid, prop), self.calc.get((sid, prop)))
    def get_comp(self, sid): return self.comp.get(sid, {})
    def solve(self): return True
