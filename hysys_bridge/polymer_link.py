"""Polymer stream attributes by the method of moments, as used by Aspen Polymers (Liu and Sharma, "Introduction to Integrated Process Modeling,
Advanced Control, and Data Analytics in Optimizing Polyolefin Manufacturing", Chapter 1, 2023, sections 1.1.2 and 1.1.3, equations 1.1 to 1.13).
A pure calculator, no simulator and no dependencies: it checks the stream-initialisation and mixing arithmetic that Aspen Polymers does, so an Aspen result
(or a printed table) can be tested against the definitions.

Definitions (n = segments in a chain, [Pn] = chain concentration): mu_i = sum n^i [Pn]. ZMOM = mu_0 (total chains), FMOM = mu_1 (total segments),
SMOM = mu_2. DPN = FMOM/ZMOM, DPW = SMOM/FMOM, PDI = DPW/DPN = MWW/MWN, MWN = DPN x MWSEG, MWW = DPW x MWSEG. Moments are additive when streams mix, so
mixing is exact in this segment-moment convention. Note (derived from the definitions above, not stated in the chapter): because MWW = DPW x MWSEG uses the mixture's
average segment molar mass, the mixed MWW is NOT the mass-weighted average of the inputs' MWW when their segment compositions differ; the printed Aspen table follows
the segment-moment convention. Nothing is guessed: every input is required, and MWW below MWN (PDI below 1) is refused
because it is impossible by definition.
"""
from __future__ import annotations


def chain_statistics(counts: dict[int, float]) -> dict:
    """counts = {n: [Pn]}. The chapter's toy example (one chain each of 3, 4 and 5 segments) gives DPN 4, DPW 4.17, PDI 1.04."""
    if not counts or any(n <= 0 or c < 0 for n, c in counts.items()): raise ValueError("counts must map positive chain lengths to non-negative concentrations")
    mu = [sum(n ** i * c for n, c in counts.items()) for i in range(3)]
    if mu[0] <= 0: raise ValueError("no chains")
    dpn, dpw = mu[1] / mu[0], mu[2] / mu[1]
    return {"ZMOM": mu[0], "FMOM": mu[1], "SMOM": mu[2], "DPN": dpn, "DPW": dpw, "PDI": dpw / dpn}


def init_stream(mass_kg_s: float, seg_mole_fractions: dict[str, float], seg_mw: dict[str, float], mwn: float, mww: float | None = None, smom_kmol_s: float | None = None) -> dict:
    """Aspen's stream initialisation (section 1.1.3). seg_mw in kg/kmol. Give MWW, or SMOM directly (kmol/s) when the second moment is known another way."""
    if mass_kg_s <= 0 or mwn <= 0: raise ValueError("mass flow and MWN must be positive")
    if set(seg_mole_fractions) != set(seg_mw): raise ValueError("seg_mole_fractions and seg_mw must name the same segments")
    if abs(sum(seg_mole_fractions.values()) - 1.0) > 1e-6: raise ValueError(f"segment mole fractions sum to {sum(seg_mole_fractions.values()):.6f}, not 1")
    if (mww is None) == (smom_kmol_s is None): raise ValueError("give exactly one of mww and smom_kmol_s")
    mwseg = sum(x * seg_mw[k] for k, x in seg_mole_fractions.items())
    zmom, fmom = mass_kg_s / mwn, mass_kg_s / mwseg
    if mww is not None:
        if mww < mwn: raise ValueError(f"MWW {mww} is below MWN {mwn}: PDI would be {mww / mwn:.3f}, below 1, which is impossible by definition (PDI = MWW/MWN >= 1)")
        smom = (mww / mwseg) * fmom
    else:
        smom = smom_kmol_s
        if smom * zmom < fmom ** 2 * (1 - 1e-9): raise ValueError("second moment too small: it would make PDI below 1")
    return _finish({"mass_kg_s": mass_kg_s, "ZMOM": zmom, "FMOM": fmom, "SMOM": smom, "SFLOW": {k: fmom * x for k, x in seg_mole_fractions.items()}})


def _finish(s: dict) -> dict:
    mwseg = s["mass_kg_s"] / s["FMOM"]; dpn, dpw = s["FMOM"] / s["ZMOM"], s["SMOM"] / s["FMOM"]
    s.update(MWSEG=mwseg, DPN=dpn, DPW=dpw, PDI=dpw / dpn, MWN=dpn * mwseg, MWW=dpw * mwseg, SFRAC={k: v / s["FMOM"] for k, v in s["SFLOW"].items()})
    return s


def mix(streams: list[dict]) -> dict:
    """Adiabatic or not, moments, segment flows and mass simply add; the attributes of the mixed stream follow from the definitions."""
    if len(streams) < 2: raise ValueError("mixing needs at least two streams")
    segs = set(streams[0]["SFLOW"])
    if any(set(s["SFLOW"]) != segs for s in streams): raise ValueError("streams must carry the same segments")
    tot = {"mass_kg_s": sum(s["mass_kg_s"] for s in streams), "ZMOM": sum(s["ZMOM"] for s in streams), "FMOM": sum(s["FMOM"] for s in streams),
           "SMOM": sum(s["SMOM"] for s in streams), "SFLOW": {k: sum(s["SFLOW"][k] for s in streams) for k in segs}}
    return _finish(tot)


def _num(a, k):
    if k not in a: raise ValueError(f"{k} is required")
    return float(a[k])


def _init(a):
    for k in ("seg_mole_fractions", "seg_mw_kg_kmol"):
        if not isinstance(a.get(k), dict): raise ValueError(f"{k} is required (an object keyed by segment name)")
    return init_stream(_num(a, "mass_kg_s"), a["seg_mole_fractions"], a["seg_mw_kg_kmol"], _num(a, "mwn"), a.get("mww"), a.get("smom_kmol_s"))


def t_stream(a):
    s = _init(a)
    return {**s, "note": "Liu and Sharma (2023) chapter 1, equations 1.1 to 1.13; kmol/s and kg/kmol; ZMOM total chains, FMOM total segments, SMOM second moment"}


def t_mix(a):
    streams = a.get("streams")
    if not isinstance(streams, list): raise ValueError("streams must be a list of stream specifications")
    built = [_init(x) for x in streams]
    m = mix(built)
    return {**m, "inputs": built, "note": "exact moment mixing; compare MWN, MWW and PDI with an Aspen Polymers mixer. PDI is always at least 1"}


def _s(props, req): return {"type": "object", "properties": props, "required": req, "additionalProperties": False}
_stream_props = {"mass_kg_s": {"type": "number"}, "seg_mole_fractions": {"type": "object", "additionalProperties": {"type": "number"}}, "seg_mw_kg_kmol": {"type": "object", "additionalProperties": {"type": "number"}},
                 "mwn": {"type": "number"}, "mww": {"type": "number"}, "smom_kmol_s": {"type": "number"}}
TOOLS = {
    "polymer_stream_attributes": (t_stream, "Initialise a polymer stream the way Aspen Polymers does: from mass flow, segment mole fractions, segment molar masses, MWN and MWW (or the second moment), return DPN, DPW, PDI, "
                                            "ZMOM, FMOM, SMOM and segment flows. Refuses MWW below MWN (PDI below 1 is impossible). Pure arithmetic, no simulator.",
                                  _s(_stream_props, ["mass_kg_s", "seg_mole_fractions", "seg_mw_kg_kmol", "mwn"])),
    "polymer_mix": (t_mix, "Mix two or more polymer streams by adding their moments and return MWN, MWW, PDI and segment fractions of the mixture: a check on an Aspen Polymers mixer. Each stream as in polymer_stream_attributes.",
                    _s({"streams": {"type": "array", "items": _s(_stream_props, ["mass_kg_s", "seg_mole_fractions", "seg_mw_kg_kmol", "mwn"])}}, ["streams"])),
}
