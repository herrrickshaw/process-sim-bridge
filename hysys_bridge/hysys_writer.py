"""Write validated specs to HYSYS and read every value back.

Policy (important):
  * Only INDEPENDENT specs are written: feed T,P,one flow basis,composition; plus the
    outlet spec that defines each simple unit (pump/valve/compressor: P_out;
    heater/cooler: T_out and P_out).
  * Everything else in the H&MB (enthalpy, vapour fraction, downstream flows, ...) is
    NOT written - HYSYS computes it and hmb_check.py compares against the H&MB.
    Over-specifying streams is how DOF errors and silent overrides creep in.
"""
from __future__ import annotations
import csv
from dataclasses import dataclass
from .ir import Flowsheet, Stream
from .backend import Backend

REL_TOL = {"T": 1e-6, "P": 1e-6, "mass": 1e-6, "mol": 1e-6, "vol": 1e-6}


@dataclass
class Row:
    stream: str; prop: str; source: str; extracted: float; readback: float | None; status: str


def flow_spec(s: Stream):
    for k, v in (("mass", s.mass_flow_kg_h), ("mol", s.molar_flow_kmol_h), ("vol", s.vol_flow_m3_h)):
        if v is not None:
            return k, v
    return None


def plan_specs(fs: Flowsheet) -> list[tuple[str, str, float]]:
    """[(stream, prop, value)] - the independent specs only."""
    plan = []
    for s in fs.streams.values():
        if s.kind == "feed":
            if s.T_C is not None: plan.append((s.id, "T", s.T_C))
            if s.P_kPa is not None: plan.append((s.id, "P", s.P_kPa))
            f = flow_spec(s)
            if f: plan.append((s.id, *f))
    for u in fs.units.values():
        for o in u.outlets:
            so = fs.streams[o]
            if u.type in ("pump", "valve", "compressor") and so.P_kPa is not None:
                plan.append((o, "P", so.P_kPa))
            if u.type in ("heater", "cooler"):
                if so.T_C is not None: plan.append((o, "T", so.T_C))
                if so.P_kPa is not None: plan.append((o, "P", so.P_kPa))
    return plan


def write(fs: Flowsheet, be: Backend, audit_csv: str | None = None) -> list[Row]:
    be.new_case(fs.name, fs.fluid_package, fs.components)
    for sid in fs.streams: be.add_stream(sid)
    for u in fs.units.values():
        be.add_unit(u.id, u.type)
        be.connect(u.id, u.inlets, u.outlets)
    rows: list[Row] = []
    for sid, prop, val in plan_specs(fs):
        be.set(sid, prop, val)
        rb = be.get(sid, prop)
        ok = rb is not None and abs(rb - val) <= REL_TOL[prop] * max(abs(val), 1.0)
        rows.append(Row(sid, prop, fs.streams[sid].source.get(prop, "derived"), val, rb, "OK" if ok else "MISMATCH"))
    for s in fs.streams.values():
        if s.kind == "feed" and s.composition:
            be.set_comp(s.id, s.composition, s.composition_basis)
            rb = be.get_comp(s.id)
            for c, x in s.composition.items():
                got = rb.get(c)
                if s.composition_basis == "mass":
                    got = x            # HYSYS returns mole basis; compared after solve instead
                ok = got is not None and abs(got - x) < 1e-9
                rows.append(Row(s.id, f"x[{c}]", s.source.get(f"x[{c}]", ""), x, got, "OK" if ok else "MISMATCH"))
    if audit_csv:
        with open(audit_csv, "w", newline="") as f:
            w = csv.writer(f); w.writerow(["stream", "prop", "source", "extracted", "readback", "status"])
            for r in rows: w.writerow([r.stream, r.prop, r.source, r.extracted, r.readback, r.status])
    return rows
