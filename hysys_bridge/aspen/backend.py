"""Aspen Plus backend: Backend-protocol adapter over a path-based `Tree`, with a real COM tree (Windows) and a mock tree.

!! AspenComTree has NEVER been run: no Aspen Plus here. Its calls follow two MIT servers read on 2026-11-20
!! (Eduardo-Mariola/aspen-plus-mcp, thirakorn-mokkawes-59/aspen-mcp): Dispatch("Apwn.Document"), SuppressDialogs, InitFromFile2 /
!! InitFromArchive2, RootModel("").FindNode(path), .Value / .SetValue(0, v), .Elements.Add / InsertRow, Engine.Run2(True) + IsRunning,
!! one COM (STA) thread. Everything else is catalogue.status "guess". Expect to fix details on a licensed Windows host.
!! Aspen reports and expects values in the flowsheet's unit set, so every write reads the node's UnitString and converts (or refuses).
Specs for DERIVED streams (outlets of a unit) are buffered and written onto the unit's own inputs at solve time, as in the DWSIM
backend, because Aspen takes outlet conditions as block inputs, not stream inputs.
"""
from __future__ import annotations
import sys
from typing import Protocol
from . import catalogue as C


class Tree(Protocol):
    def read(self, path: str): ...
    def write(self, path: str, value) -> None: ...
    def unit_of(self, path: str) -> str | None: ...
    def add_element(self, parent: str, name: str) -> None: ...
    def set_attribute(self, path: str, attr: int, value) -> None: ...
    def run(self, timeout_s: float) -> bool: ...
    def reinit(self) -> None: ...


class MockTree:
    """Dict-backed tree. Units default to a plain unit set (C, bar, kg/hr). `results` = {path: value} replayed after run().
    run() mimics Aspen's incomplete-input report only: it checks the catalogue's REQUIRED inputs, it computes nothing."""
    def __init__(self, units=None, results=None):
        self.v: dict[str, object] = {}; self.attr: dict[tuple, object] = {}; self.children: dict[str, list] = {}
        self.units = {"TEMP": "C", "PRES": "bar", "TOTAL": "kg/hr", "RES_TEMP": "C", "RES_PRES": "bar", **(units or {})}
        self.results, self.ran, self.missing = dict(results or {}), False, []

    def unit_of(self, path):
        last = path.rstrip("\\").split("\\")
        for tok in reversed(last):
            if tok in self.units: return self.units[tok]
        return None
    def read(self, path):
        if self.ran and path in self.results: return self.results[path]
        return self.v.get(path)
    def write(self, path, value): self.v[path] = value
    def add_element(self, parent, name): self.children.setdefault(parent, []).append(name); self.v[parent + "\\" + name.split("!")[0]] = name
    def set_attribute(self, path, attr, value): self.attr[(path, attr)] = value
    def reinit(self): self.ran = False
    def run(self, timeout_s):
        self.missing = []
        for name in self.children.get(C.BLOCKS_ROOT, []):
            b, model = name.split("!")
            for alt in C.REQUIRED.get(model, []):
                if not all(C.BLOCK_IN.format(b=b, k=k) in self.v for k in alt):
                    self.missing += [C.BLOCK_IN.format(b=b, k=k) for k in alt if C.BLOCK_IN.format(b=b, k=k) not in self.v]
        self.ran = not self.missing
        return self.ran


class AspenComTree:                                     # pragma: no cover  (Windows + licensed Aspen Plus only; untested)
    def __init__(self, path: str | None = None, visible: bool = False):
        if sys.platform != "win32": raise RuntimeError("AspenComTree needs Windows + a licensed Aspen Plus install")
        from concurrent.futures import ThreadPoolExecutor
        import pythoncom
        self._ex = ThreadPoolExecutor(max_workers=1, initializer=pythoncom.CoInitialize)      # all COM calls on one STA thread
        def start():
            import win32com.client
            app = win32com.client.Dispatch("Apwn.Document"); app.SuppressDialogs = True; app.Visible = visible
            if path:
                if path.lower().endswith(".bkp"): app.InitFromArchive2(path)
                else: app.InitFromFile2(path)
            return app
        self.app = self._call(start)

    def _call(self, fn): return self._ex.submit(fn).result()
    def _node(self, path):
        n = self.app.RootModel("").FindNode(path)
        if n is None: raise KeyError(f"Aspen node not found: {path}")
        return n
    def read(self, path):
        def f():
            n = self._node(path)
            try: return n.Value
            except Exception: return None
        return self._call(f)
    def write(self, path, value):
        def f():
            n = self._node(path)
            try:
                if n.Elements.Count > 0 and not isinstance(value, str): n.Elements(0).SetValue(0, value); return
            except Exception: pass
            n.SetValue(0, value)
        self._call(f)
    def unit_of(self, path):
        def f():
            try: return str(self._node(path).UnitString) or None
            except Exception: return None
        return self._call(f)
    def add_element(self, parent, name): self._call(lambda: self._node(parent).Elements.Add(name))
    def set_attribute(self, path, attr, value):
        def f():
            import pythoncom
            n = self._node(path); d = n._oleobj_.GetIDsOfNames("AttributeValue"); d = d[0] if isinstance(d, tuple) else d
            n._oleobj_.Invoke(d, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, attr, False, value)
        self._call(f)
    def reinit(self): self._call(lambda: self.app.Reinit())
    def run(self, timeout_s):
        import time
        self._call(lambda: self.app.Engine.Run2(True)); t0 = time.time()
        while self._call(lambda: self.app.Engine.IsRunning):
            if time.time() - t0 > timeout_s: self._call(lambda: self.app.Engine.Stop()); return False
            time.sleep(0.5)
        return True
    def close(self): self._ex.shutdown(wait=False)


class AspenBackend:
    readback_is_local = False        # feed values are read back from the tree; derived-stream specs are buffered until solve

    def __init__(self, tree: Tree, allow_unverified: bool = False):
        self.t, self.allow_unverified = tree, allow_unverified
        self.comps: list[str] = []
        self.blocks: dict[str, dict] = {}; self.streams: dict[str, dict] = {}
        self.flushed = False; self.last_run: dict = {}

    # -- Backend protocol -------------------------------------------------------------------------------
    def new_case(self, name, package, components):
        for p in C.PROPERTY_METHOD: self.t.write(p, package.upper().replace("PENG-ROBINSON", "PENG-ROB"))
        for c in components: self.t.add_element(C.COMPONENTS, c.upper())
        self.comps = [c.upper() for c in components]

    def add_stream(self, sid): self.t.add_element(C.STREAMS_ROOT, sid); self.streams[sid] = {"buf": {}}
    def add_unit(self, uid, utype):
        if utype not in C.BLOCK_MODEL: raise KeyError(f"no Aspen block model for {utype}")
        if utype in C.UNVERIFIED_UNITS and not self.allow_unverified:
            raise NotImplementedError(f"{utype}: block inputs are not documented in the source repos; pass allow_unverified=True and verify on Aspen")
        model = C.BLOCK_MODEL[utype][0]
        self.t.add_element(C.BLOCKS_ROOT, f"{uid}!{model}"); self.blocks[uid] = {"type": utype, "model": model, "in": [], "out": []}

    def connect(self, uid, inlets, outlets):
        b = self.blocks[uid]; inp, outs = C.PORTS[b["model"]]
        for s in inlets: self.t.add_element(C.BLOCK_PORT.format(b=uid, p=inp), s)
        for k, s in enumerate(outlets): self.t.add_element(C.BLOCK_PORT.format(b=uid, p=outs[min(k, len(outs) - 1)]), s)
        b["in"], b["out"] = list(inlets), list(outlets)

    def _feed(self, sid): return not any(sid in b["out"] for b in self.blocks.values())

    def set(self, sid, prop, value):
        if prop in ("T", "P") and self._feed(sid):
            path = C.STREAM_IN[prop].format(s=sid)
            self.t.write(path, C.convert(prop, self.t.unit_of(path), value))
        elif prop in ("mass", "mol") and self._feed(sid):
            path = C.STREAM_IN["flow"].format(s=sid); unit = self.t.unit_of(path)
            C.convert(prop, unit, 0.0)                         # raises if the node's unit is the other basis: no silent mass/mole mix-up
            self.t.write(path, C.convert(prop, unit, value))
        elif prop in ("T", "P", "mass", "mol"): pass            # derived stream: buffered below
        else: raise KeyError(f"no Aspen stream input for {prop!r}")
        self.streams[sid]["buf"][prop] = value

    def get(self, sid, prop):
        if self._feed(sid) and prop in ("T", "P"):
            path = C.STREAM_IN[prop].format(s=sid); v = self.t.read(path)
            return None if v is None else C.convert(prop, self.t.unit_of(path), v, to_aspen=False)
        return self.streams[sid]["buf"].get(prop)

    def set_comp(self, sid, x, basis):
        self.t.set_attribute(C.STREAM_FLOW_BASIS.format(s=sid), C.BASIS_ATTR, "MASS-FRAC" if basis == "mass" else "MOLE-FRAC")
        for c in self.comps: self.t.write(C.STREAM_COMP.format(s=sid, c=c), x.get(next((k for k in x if k.upper() == c), c), 0.0))
        self.streams[sid]["comp"] = dict(x)
    def get_comp(self, sid): return dict(self.streams[sid].get("comp", {}))

    # -- run ---------------------------------------------------------------------------------------------
    def flush(self):
        """Write each unit's outlet specs onto its block inputs (Aspen has no outlet-stream inputs)."""
        if self.flushed: return
        for uid, b in self.blocks.items():
            o = self.streams[b["out"][0]]["buf"] if b["out"] else {}
            spec = C.block_inputs(b["type"], o.get("T"), o.get("P"))
            for key, (q, val) in spec.items():
                path = C.BLOCK_IN.format(b=uid, k=key)
                self.t.write(path, val if q == "text" else C.convert(q, self.t.unit_of(path), val))
        self.flushed = True

    def solve(self, timeout_s: float = 300.0) -> bool:
        self.flush(); self.t.reinit()
        finished = self.t.run(timeout_s)
        self.last_run = {"finished": finished, "missing_inputs": list(getattr(self.t, "missing", [])), "blocks": self.block_status()}
        bad = [b for b, st in self.last_run["blocks"].items() if st.get("PER_ERROR") not in (None, 0, "0")]
        self.last_run["ok"] = bool(finished and not bad)
        return self.last_run["ok"]

    def block_status(self) -> dict:
        return {uid: {k: self.t.read(C.BLOCK_OUT.format(b=uid, k=k)) for k in C.BLOCK_STATUS_KEYS} for uid in self.blocks}

    def read_result(self, sid, prop):
        if prop not in C.STREAM_RES: raise NotImplementedError(f"result path for {prop!r} is not documented in the source repos (only T, P)")
        path = C.STREAM_RES[prop].format(s=sid); v = self.t.read(path)
        return None if v is None else C.convert(prop, self.t.unit_of(path), v, to_aspen=False)
