"""Backend-neutral spec-completeness check: run BEFORE any solve, so the agent cannot start a run (or 'tune') with
required inputs still unset. Targets the failure mode reported for LLM simulator agents (arXiv 2601.11650)."""
from __future__ import annotations
from ..ir import Flowsheet
from ..hysys_writer import flow_spec

REQUIRED_OUT = {"pump": ["P_kPa"], "valve": ["P_kPa"], "compressor": ["P_kPa"], "heater": ["T_C"], "cooler": ["T_C"]}


def check_specs(fs: Flowsheet) -> list[str]:
    """Human-readable list of missing required inputs (empty = complete)."""
    miss = []
    for s in fs.streams.values():
        if s.kind != "feed": continue
        if s.T_C is None: miss.append(f"feed {s.id}: temperature")
        if s.P_kPa is None: miss.append(f"feed {s.id}: pressure")
        if flow_spec(s) is None: miss.append(f"feed {s.id}: flow rate")
        if not s.composition: miss.append(f"feed {s.id}: composition")
    for u in fs.units.values():
        for attr in REQUIRED_OUT.get(u.type, []):
            for o in u.outlets:
                if getattr(fs.streams[o], attr) is None:
                    miss.append(f"{u.type} {u.id}: outlet {o} {attr}")
        if not u.outlets or (u.type != "mixer" and not u.inlets):
            miss.append(f"{u.type} {u.id}: not fully connected")
    return miss
