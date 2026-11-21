"""Aspen Plus node-path catalogue: block models, ports, input/output paths, unit conversion.

Source: read (not run) from the MIT-licensed Eduardo-Mariola/aspen-plus-mcp and thirakorn-mokkawes-59/aspen-mcp, 2026-11-20:
their docs/blocks/*.md (heater, pump, mixer, fsplit, flash2, compr) and tools/*.py. Copyright (c) 2026 Eduardo Mariola and
Aspen Plus MCP contributors, MIT. NOTHING HERE HAS BEEN RUN against Aspen Plus (none on this machine): every entry carries a
`status`: "doc" = taken from those repos' block docs / working code, "guess" = inferred, to be verified on a licensed host.
"""
from __future__ import annotations

# our unit type -> (Aspen block model string, status)
BLOCK_MODEL = {"mixer": ("MIXER", "doc"), "splitter": ("FSPLIT", "doc"), "heater": ("HEATER", "doc"), "cooler": ("HEATER", "doc"),
               "separator": ("FLASH2", "doc"), "pump": ("PUMP", "guess"), "valve": ("VALVE", "guess"), "compressor": ("COMPR", "guess")}
# types whose block inputs are not documented in the source repos (valve.md was a 404, compr not mapped): refused unless allowed
UNVERIFIED_UNITS = {"valve", "compressor"}
# model -> (inlet port, outlet ports in order)
PORTS = {"MIXER": ("F", ["P"]), "FSPLIT": ("F", ["P"]), "HEATER": ("F", ["P"]), "PUMP": ("F", ["P"]),
         "VALVE": ("F", ["P"]), "COMPR": ("F", ["P"]), "FLASH2": ("F", ["V", "L"])}

STREAM_IN = {"T": r"\Data\Streams\{s}\Input\TEMP\MIXED", "P": r"\Data\Streams\{s}\Input\PRES\MIXED", "flow": r"\Data\Streams\{s}\Input\TOTAL"}   # TOTAL as used by the reference server (guess: Aspen docs call it TOTFLOW)
STREAM_FLOW_BASIS = r"\Data\Streams\{s}\Input\FLOW\MIXED"            # BASIS attribute (index 13) + per-component values below it
STREAM_COMP = r"\Data\Streams\{s}\Input\FLOW\MIXED\{c}"
STREAM_RES = {"T": r"\Data\Streams\{s}\Output\RES_TEMP", "P": r"\Data\Streams\{s}\Output\RES_PRES"}   # only these two documented
BLOCK_IN = r"\Data\Blocks\{b}\Input\{k}"
BLOCK_OUT = r"\Data\Blocks\{b}\Output\{k}"
BLOCK_PORT = r"\Data\Blocks\{b}\Ports\{p}"
BLOCK_STATUS_KEYS = ("BLKSTAT", "PER_ERROR", "PROPSTAT")            # documented as readable after a run
PROPERTY_METHOD = (r"\Data\Properties\Specifications\Input\GBASEOPSET", r"\Data\Properties\Specifications\Input\GOPSETNAME")
COMPONENTS = r"\Data\Components\Specifications\Input\TYPE"
BLOCKS_ROOT, STREAMS_ROOT = r"\Data\Blocks", r"\Data\Streams"
BASIS_ATTR = 13

# block inputs we write from our IR (outlet spec of a simple unit), and what must be present before a run
def block_inputs(utype: str, out_T_C=None, out_P_kPa=None, in_P_kPa=None) -> dict:
    """{input key: (our quantity, value in our units)} for the outlet specs of one unit. Pressure is ABSOLUTE and must be > 0
    (in Aspen a value <= 0 means a pressure drop)."""
    if utype in ("heater", "cooler"):
        d = {}
        if out_T_C is not None: d["TEMP"] = ("T", out_T_C)
        if out_P_kPa is not None: d["PRES"] = ("P", out_P_kPa)
        return d
    if utype == "pump" and out_P_kPa is not None: return {"OPT_SPEC": ("text", "PRES"), "PRES": ("P", out_P_kPa)}
    if utype == "separator":
        d = {}
        if out_T_C is not None: d["TEMP"] = ("T", out_T_C)
        if out_P_kPa is not None: d["PRES"] = ("P", out_P_kPa)
        return d
    return {}

REQUIRED = {"HEATER": [["TEMP", "PRES"]], "PUMP": [["PRES"]], "FLASH2": [["TEMP", "PRES"]], "MIXER": [], "FSPLIT": []}   # lists of alternatives

TEMP_UNITS = {"C": (lambda c: c, lambda v: v), "K": (lambda c: c + 273.15, lambda v: v - 273.15),
              "F": (lambda c: c * 9 / 5 + 32, lambda v: (v - 32) * 5 / 9)}
PRES_UNITS = {"bar": (lambda k: k / 100, lambda v: v * 100), "kPa": (lambda k: k, lambda v: v), "Pa": (lambda k: k * 1e3, lambda v: v / 1e3),
              "atm": (lambda k: k / 101.325, lambda v: v * 101.325), "MPa": (lambda k: k / 1e3, lambda v: v * 1e3),
              "psi": (lambda k: k / 6.894757, lambda v: v * 6.894757)}
MASS_FLOW_UNITS = {"kg/hr": (lambda x: x, lambda v: v), "kg/sec": (lambda x: x / 3600, lambda v: v * 3600), "tonne/hr": (lambda x: x / 1000, lambda v: v * 1000)}
MOLE_FLOW_UNITS = {"kmol/hr": (lambda x: x, lambda v: v), "mol/sec": (lambda x: x * 1000 / 3600, lambda v: v * 3600 / 1000)}
QUANTITY_UNITS = {"T": TEMP_UNITS, "P": PRES_UNITS, "mass": MASS_FLOW_UNITS, "mol": MOLE_FLOW_UNITS}


def convert(quantity: str, unit: str, value: float, to_aspen: bool = True) -> float:
    """Our units (C, kPa, kg/h, kmol/h) <-> the unit string the Aspen node reports. Unknown unit string: refuse, never guess."""
    table = QUANTITY_UNITS[quantity]
    u = (unit or "").strip().replace("-", "")
    key = next((k for k in table if k.lower() == u.lower()), None)
    if key is None: raise ValueError(f"Aspen node unit {unit!r} is not a known {quantity} unit {sorted(table)}; change the unit set or extend the catalogue")
    return table[key][0 if to_aspen else 1](value)
