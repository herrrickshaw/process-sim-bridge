"""P&ID / PFD image -> ir.Flowsheet (topology draft) with a vision LLM.

Follows the paper's staged extraction: pass 1 lists units; pass 2 lists streams and may only
reference pass-1 unit ids (limits hallucinated equipment). Output is ALWAYS a draft:
every unit/stream carries flag 'needs-signoff', and numeric values are NOT taken from the
drawing (take them from the H&MB; merge with merge_values()).

Needs: pip install anthropic pymupdf ; env ANTHROPIC_API_KEY. `ask` is injectable for tests.
"""
from __future__ import annotations
import base64, json, re
from .ir import Flowsheet, Stream, Unit
from .extract_hmb import guess_unit_type

MODEL = "claude-sonnet-5-5"
UNIT_TYPES = ["mixer", "splitter", "pump", "heater", "cooler", "valve", "compressor",
              "separator", "column", "reactor", "unknown"]

P1 = ("List every unit operation / equipment item visible in this process diagram, left to right. "
      "Use the tag printed on the drawing if any, otherwise invent 'U1','U2'.. Do NOT infer equipment "
      "that is not drawn. Self-check each item is visible. Return ONLY JSON: "
      '{"units":[{"id":str,"type":one of %s,"label":str}]}' % UNIT_TYPES)
P2 = ("Units already identified: {units}. List every material stream (line with an arrow). "
      "src and dst must be one of these unit ids, or null for a feed entering / product leaving the "
      "diagram. Use printed stream numbers if present. Return ONLY JSON: "
      '{{"streams":[{{"id":str,"src":str|null,"dst":str|null}}]}}')


def _image_b64(path: str, page=1, dpi=200) -> tuple[str, str]:
    if path.lower().endswith(".pdf"):
        import fitz
        return base64.b64encode(fitz.open(path)[page - 1].get_pixmap(dpi=dpi).tobytes("png")).decode(), "image/png"
    mt = "image/png" if path.lower().endswith("png") else "image/jpeg"
    return base64.b64encode(open(path, "rb").read()).decode(), mt


def anthropic_ask(image_path: str, page=1):                              # pragma: no cover
    import anthropic
    client = anthropic.Anthropic()
    b64, mt = _image_b64(image_path, page)

    def ask(prompt: str) -> str:
        r = client.messages.create(model=MODEL, max_tokens=4000, messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}},
            {"type": "text", "text": prompt}]}])
        return r.content[0].text
    return ask


def _json(txt: str) -> dict:
    m = re.search(r"\{.*\}", txt, re.S)
    if not m: raise ValueError(f"no JSON in model reply: {txt[:120]!r}")
    return json.loads(m.group(0))


def parse_two_pass(ask, name="pid") -> Flowsheet:
    u = _json(ask(P1))["units"]
    ids = [x["id"] for x in u]
    if len(ids) != len(set(ids)): raise ValueError(f"duplicate unit ids from model: {ids}")
    fs = Flowsheet(name=name)
    for x in u:
        t = x.get("type") if x.get("type") in UNIT_TYPES else guess_unit_type(x["id"])
        fs.units[x["id"]] = Unit(id=x["id"], type=t, flags=["needs-signoff"])
    s = _json(ask(P2.format(units=ids)))["streams"]
    for x in s:
        for end in ("src", "dst"):
            if x.get(end) is not None and x[end] not in fs.units:
                raise ValueError(f"stream {x['id']}: {end}={x[end]!r} not a known unit (hallucination)")
        if x["id"] in fs.streams: raise ValueError(f"duplicate stream id {x['id']}")
        st = Stream(id=x["id"], src=x.get("src"), dst=x.get("dst"))
        st.kind = "feed" if st.src is None else ("product" if st.dst is None else "intermediate")
        fs.streams[st.id] = st
    fs.relink()
    return fs


def extract(image_path: str, page=1, ask=None) -> Flowsheet:
    return parse_two_pass(ask or anthropic_ask(image_path, page), name=image_path.rsplit("/", 1)[-1])


def merge_values(topology: Flowsheet, hmb: Flowsheet) -> list[str]:
    """Copy numeric specs from H&MB onto the P&ID topology; report every disagreement.
    Matching is by stream id; connectivity in H&MB (From/To) is compared, never silently merged."""
    notes = []
    for sid, hs in hmb.streams.items():
        ts = topology.streams.get(sid)
        if ts is None:
            notes.append(f"stream {sid} in H&MB but not on P&ID"); continue
        if (hs.src, hs.dst) != (ts.src, ts.dst) and (hs.src or hs.dst):
            notes.append(f"stream {sid}: P&ID {ts.src}->{ts.dst} vs H&MB {hs.src}->{hs.dst}")
        for f in ("T_C", "P_kPa", "mass_flow_kg_h", "molar_flow_kmol_h", "vol_flow_m3_h",
                  "composition", "composition_basis", "checks", "source", "confidence"):
            setattr(ts, f, getattr(hs, f))
    for sid in topology.streams.keys() - hmb.streams.keys():
        notes.append(f"stream {sid} on P&ID but not in H&MB")
    topology.components = hmb.components
    return notes
