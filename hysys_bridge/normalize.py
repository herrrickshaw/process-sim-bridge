"""Rule-based normalisation (the paper's Agent A3): deterministic, no LLM.

1. Implicit junctions: >1 stream entering a unit that accepts one inlet
   (pump, heater, cooler, valve, compressor, separator-with-1-feed) -> insert a mixer.
2. Implicit splits: >1 stream leaving a non-splitting unit's single outlet -> insert a splitter.
"""
from .ir import Flowsheet, Stream, Unit

SINGLE_IN = {"pump", "heater", "cooler", "valve", "compressor", "expander"}
MULTI_IN = {"mixer", "separator", "column", "reactor"}


def normalize(fs: Flowsheet) -> list[str]:
    log: list[str] = []
    fs.relink()
    for u in list(fs.units.values()):
        if u.type in SINGLE_IN and len(u.inlets) > 1:
            mx = Unit(id=f"MX-{u.id}", type="mixer")
            fs.units[mx.id] = mx
            out = Stream(id=f"{mx.id}-out", kind="intermediate", src=mx.id, dst=u.id)
            for sid in u.inlets:
                fs.streams[sid].dst = mx.id
            fs.streams[out.id] = out
            log.append(f"inserted mixer {mx.id} ahead of {u.id} (merged {u.inlets})")
            fs.relink()
    for u in list(fs.units.values()):
        if u.type in {"pump", "heater", "cooler", "valve", "compressor", "mixer"} and len(u.outlets) > 1:
            sp = Unit(id=f"SP-{u.id}", type="splitter")
            fs.units[sp.id] = sp
            mid = Stream(id=f"{sp.id}-in", src=u.id, dst=sp.id)
            for sid in u.outlets:
                fs.streams[sid].src = sp.id
            fs.streams[mid.id] = mid
            log.append(f"inserted splitter {sp.id} after {u.id}")
            fs.relink()
    for u in fs.units.values():
        if u.type == "unknown":
            u.flags.append("unrecognised-symbol: engineer must assign type")
    return log
