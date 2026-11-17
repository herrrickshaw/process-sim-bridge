"""Intermediate representation: directed graph G=(V,E) of units and streams."""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Stream:
    id: str
    kind: str = "intermediate"            # feed | intermediate | product
    src: Optional[str] = None             # unit id or None for feeds
    dst: Optional[str] = None             # unit id or None for products
    # SPEC values, stored in canonical SI-ish units (see units.py)
    T_C: Optional[float] = None
    P_kPa: Optional[float] = None
    mass_flow_kg_h: Optional[float] = None
    molar_flow_kmol_h: Optional[float] = None
    vol_flow_m3_h: Optional[float] = None
    composition: dict[str, float] = field(default_factory=dict)   # mole fractions
    composition_basis: str = "mole"       # mole | mass (mass converted by validate)
    # CHECK values from the H&MB (never written to HYSYS)
    checks: dict[str, float] = field(default_factory=dict)        # e.g. vapour_fraction, enthalpy_kJ_h
    # provenance for audit trail: field -> "file p3 r12 c4"
    source: dict[str, str] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)


@dataclass
class Unit:
    id: str
    type: str                              # mixer|splitter|pump|heater|cooler|valve|separator|column|...
    params: dict[str, float] = field(default_factory=dict)
    inlets: list[str] = field(default_factory=list)
    outlets: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)   # e.g. "unrecognised-symbol"


@dataclass
class Flowsheet:
    name: str = "case"
    fluid_package: str = "Peng-Robinson"
    components: list[str] = field(default_factory=list)
    streams: dict[str, Stream] = field(default_factory=dict)
    units: dict[str, Unit] = field(default_factory=dict)

    def to_json(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def from_json(cls, path: str) -> "Flowsheet":
        with open(path) as f:
            d = json.load(f)
        fs = cls(d["name"], d["fluid_package"], d["components"])
        fs.streams = {k: Stream(**v) for k, v in d["streams"].items()}
        fs.units = {k: Unit(**v) for k, v in d["units"].items()}
        return fs

    def relink(self) -> None:
        """Rebuild unit inlets/outlets from stream src/dst (single source of truth)."""
        for u in self.units.values():
            u.inlets, u.outlets = [], []
        for s in self.streams.values():
            if s.dst in self.units:
                self.units[s.dst].inlets.append(s.id)
            if s.src in self.units:
                self.units[s.src].outlets.append(s.id)
