"""Flowsheet IR <-> DEXPI-style Proteus XML (P&ID topology + stream data).

Structure follows the Proteus layout used by DEXPI P&ID exchange: root <PlantModel> (no
namespace, UTF-8), <Equipment> with <Nozzle> children, <PipingNetworkSystem> containing one
<PipingNetworkSegment> per stream, and <Connection FromID=.. ToID=..> pointing at nozzles.
Stream/unit numbers are carried as <GenericAttributes>.

STATUS - read before relying on it:
  * Written from public descriptions of the format (AVEVA/CADMATIC docs, the Proteus repo notes).
    CHECKED against pyDEXPI 2.1.0 (ProteusSerializer): the sample file loads, Mixer/HeatExchanger are
    recognised, and nozzle-to-nozzle connections resolve. NOT checked against the Proteus XSD or in any
    commercial P&ID tool.
  * Equipment classes (all verified to be recognised by pyDEXPI's Proteus loader, which silently turns unknown class
    names into the generic ProcessEquipment): pump CentrifugalPump, compressor CentrifugalCompressor,
    heater/cooler HeatExchanger, separator Separator, column ProcessColumn, mixer Mixer, reactor PressureVessel
    (DEXPI has no reactor class; PressureVessel is a judgement call, change CLASS_MAP if you prefer
    ProcessEquipment), unknown ProcessEquipment.
  * valve and splitter are NOT equipment in DEXPI: they are piping components inside a segment. A valve (1 in, 1 out)
    becomes a GlobeValve (OperatedValve for FV/PV/LV/TV/... tags) item and a splitter (1 in, >=2 out) a PipeTee item
    in the "run" segment; the branch segments start at the tee. Streams on either side of such a component share one
    segment (the in-stream's id); the folded streams' data lives in StreamData.<id> sets and the component's
    HysysBridge set records InStream/OutStream so load() can split the run back apart. A valve/splitter with another
    in/out count falls back to ProcessEquipment. The DEXPI-native attributes (OperatingTemperature) describe the
    segment's first stream only.
  * There is no drawing geometry: this is a topology + data export, not a drawable P&ID.
  * Feed/product boundaries are open segment ends (no connector elements).
"""
from __future__ import annotations
import datetime
import xml.etree.ElementTree as ET
from .ir import Flowsheet, Stream, Unit

RDL = "http://sandbox.dexpi.org/rdl/"
CLASS_MAP = {
    "pump": "CentrifugalPump", "compressor": "CentrifugalCompressor", "heater": "HeatExchanger",
    "cooler": "HeatExchanger", "separator": "Separator", "column": "ProcessColumn", "reactor": "PressureVessel",
    "valve": "ProcessEquipment", "mixer": "Mixer", "splitter": "ProcessEquipment", "unknown": "ProcessEquipment",
}
# many IR types share one class (heater/cooler): keep the IR type in an attribute to round-trip
REV_CLASS = {v: k for k, v in CLASS_MAP.items() if k not in ("cooler", "valve", "splitter", "unknown")}
CONTROL_TAGS = ("FV", "PV", "LV", "TV", "FCV", "PCV", "LCV", "TCV", "XV")


def collapsible(u: Unit) -> bool:
    """Units encoded as piping components inside a segment (valve 1-in/1-out, splitter 1-in/>=2-out)."""
    return (u.type == "valve" and len(u.inlets) == 1 and len(u.outlets) == 1) or \
           (u.type == "splitter" and len(u.inlets) == 1 and len(u.outlets) >= 2)


def component_class(u: Unit) -> str:
    if u.type == "splitter": return "PipeTee"
    return "OperatedValve" if u.id.upper().startswith(CONTROL_TAGS) else "GlobeValve"
STREAM_FIELDS = [("T_C", "Temperature", "degC"), ("P_kPa", "Pressure", "kPa"),
                 ("mass_flow_kg_h", "MassFlow", "kg/h"), ("molar_flow_kmol_h", "MolarFlow", "kmol/h"),
                 ("vol_flow_m3_h", "VolumeFlow", "m3/h")]


def _ga(parent: ET.Element, set_name: str, items: list[tuple[str, str, str]]):
    if not items: return
    g = ET.SubElement(parent, "GenericAttributes", Set=set_name, Number=str(len(items)))
    for name, value, units in items:
        ET.SubElement(g, "GenericAttribute", Name=name, Format="double", Value=value, **({"Units": units} if units else {}))


def _eid(uid): return f"EQ-{uid}"


# ---- stream/unit data -> real DEXPI P&ID attributes ---------------------------------------------------
# What a DEXPI P&ID (pyDEXPI 2.1.0 class model) can actually hold:
#   PipingNetworkSegment: operatingTemperature (quantity), fluidCode (string)
#   CentrifugalPump:      differentialPressure, designVolumeFlowRate
#   HeatExchanger:        designHeatFlowRate
#   Separator:            designVolumeFlowRate
# It has NO attribute for stream pressure, mass/molar flow, or composition: those belong to the separate
# DEXPI *Process* model (Stream/Composition/MaterialState) that Proteus P&ID XML does not carry, so they stay in
# the custom StreamData set (ignored by standard readers).
Q = tuple  # (Name, value-as-str, units, format)


def _num(name, value, units): return (name, repr(float(value)), units, "double")


def segment_dexpi(s: Stream) -> list[Q]:
    out = []
    if s.T_C is not None: out.append(_num("OperatingTemperature", s.T_C, "DegreeCelsius"))
    if s.composition:                                     # label only: the dominant component, not a piping fluid code
        out.append(("FluidCode", max(s.composition, key=s.composition.get), "", "string"))
    return out


def unit_dexpi(fs: Flowsheet, u: Unit) -> list[Q]:
    ins = [fs.streams[i] for i in u.inlets]; outs = [fs.streams[o] for o in u.outlets]
    out = []
    if u.type == "pump":
        if len(ins) == 1 and len(outs) == 1 and ins[0].P_kPa is not None and outs[0].P_kPa is not None:
            out.append(_num("DifferentialPressure", outs[0].P_kPa - ins[0].P_kPa, "Kilopascal"))   # gauge difference
        if ins and all(i.vol_flow_m3_h is not None for i in ins):
            out.append(_num("DesignVolumeFlowRate", sum(i.vol_flow_m3_h for i in ins), "MetreCubedPerHour"))
    elif u.type in ("heater", "cooler"):
        h_in = [i.checks.get("enthalpy_kJ_h") for i in ins]; h_out = [o.checks.get("enthalpy_kJ_h") for o in outs]
        if ins and outs and None not in h_in + h_out:
            out.append(_num("DesignHeatFlowRate", abs(sum(h_out) - sum(h_in)) / 3600.0, "Kilowatt"))   # |duty|, kJ/h -> kW
    elif u.type == "separator":
        if ins and all(i.vol_flow_m3_h is not None for i in ins):
            out.append(_num("DesignVolumeFlowRate", sum(i.vol_flow_m3_h for i in ins), "MetreCubedPerHour"))
    return out


def _dexpi_set(parent: ET.Element, items: list[Q]):
    if not items: return
    g = ET.SubElement(parent, "GenericAttributes", Set="DexpiAttributes", Number=str(len(items)))
    for name, value, units, fmt in items:
        ET.SubElement(g, "GenericAttribute", Name=name, Format=fmt, Value=value, **({"Units": units} if units else {}))


def export(fs: Flowsheet, path: str | None = None) -> str:
    fs.relink()
    root = ET.Element("PlantModel")
    now = datetime.datetime.now(datetime.timezone.utc)
    ET.SubElement(root, "PlantInformation", Application="Dexpi", Discipline="PID", Name=fs.name, SchemaVersion="4.1",
                  Date=now.strftime("%Y-%m-%d"), Time=now.strftime("%H:%M:%S"), OriginatingSystem="hysys_bridge",
                  OriginatingSystemVendor="local", OriginatingSystemVersion="0.1", Is3D="no", Units="Metric")
    ET.SubElement(root, "Drawing", Name=fs.name, Presentation="none")
    nozzle_of: dict[tuple[str, str, str], str] = {}                 # (unit, stream, 'in'|'out') -> nozzle id
    col = {uid for uid, u in fs.units.items() if collapsible(u)}
    for uid, u in fs.units.items():
        if uid in col: continue                                       # written as a piping component in its segment
        cls = CLASS_MAP.get(u.type, "ProcessEquipment")
        eq = ET.SubElement(root, "Equipment", ID=_eid(uid), TagName=uid, ComponentClass=cls,
                           ComponentClassURI=RDL + cls, ComponentName=uid)
        g = ET.SubElement(eq, "GenericAttributes", Set="HysysBridge", Number="1")
        ET.SubElement(g, "GenericAttribute", Name="IRType", Format="string", Value=u.type)
        # pyDEXPI reads tagName and the design attributes from the DexpiAttributes set
        _dexpi_set(eq, [("TagNameAssignmentClass", uid, "", "string")] + unit_dexpi(fs, u))
        for k, (sid, d) in enumerate([(s, "in") for s in u.inlets] + [(s, "out") for s in u.outlets], start=1):
            nid = f"{_eid(uid)}-N{k}"
            ET.SubElement(eq, "Nozzle", ID=nid, TagName=f"N{k}", ComponentClass="Nozzle", ComponentClassURI=RDL + "Nozzle")
            nozzle_of[(uid, sid, d)] = nid
        for key, val in u.params.items():
            _ga(eq, "Parameters", [(key, repr(float(val)), "")])
    pns = ET.SubElement(root, "PipingNetworkSystem", ID="PNS-1", ComponentClass="PipingNetworkSystem",
                        ComponentClassURI=RDL + "PipingNetworkSystem")
    def stream_sets(seg, st: Stream, suffix: str = ""):
        _ga(seg, "StreamData" + suffix, [(name, repr(getattr(st, f)), unit) for f, name, unit in STREAM_FIELDS if getattr(st, f) is not None]
            + [(f"x[{c}]", repr(v), "") for c, v in st.composition.items()])
        if st.checks:
            _ga(seg, "HMBChecks" + suffix, [(k, repr(v), "") for k, v in st.checks.items()])

    starts = [st for st in fs.streams.values() if st.src not in col or fs.units[st.src].outlets[0] != st.id]
    covered: set[str] = set()
    for s0 in starts:                                                 # one segment per run of streams
        chain, comps, cur = [s0], [], s0
        while cur.dst in col:
            u = fs.units[cur.dst]
            if u in comps: raise ValueError(f"cycle of valves/splitters through {u.id}: unsupported")
            comps.append(u); cur = fs.streams[u.outlets[0]]; chain.append(cur)
        covered |= {x.id for x in chain}
        seg = ET.SubElement(pns, "PipingNetworkSegment", ID=f"SEG-{s0.id}", ComponentClass="PipingNetworkSegment",
                            ComponentClassURI=RDL + "PipingNetworkSegment", TagName=s0.id)
        for k, u in enumerate(comps):
            cc = component_class(u)
            pc = ET.SubElement(seg, "PipingComponent", ID=_eid(u.id), TagName=u.id, ComponentClass=cc, ComponentClassURI=RDL + cc)
            g = ET.SubElement(pc, "GenericAttributes", Set="HysysBridge", Number="3")
            for nm, val in (("IRType", u.type), ("InStream", chain[k].id), ("OutStream", chain[k + 1].id)):
                ET.SubElement(g, "GenericAttribute", Name=nm, Format="string", Value=val)
        if s0.src is None: frm = None
        elif s0.src in col: frm = _eid(s0.src)                        # branch leaving a tee
        else: frm = nozzle_of[(s0.src, s0.id, "out")]
        to = None if cur.dst is None else nozzle_of[(cur.dst, cur.id, "in")]
        # A diagram boundary (feed in / product out) is an OPEN end of the segment: pyDEXPI loads that cleanly,
        # whereas an in-segment PipeOffPageConnector next to an external nozzle raised parse errors.
        ET.SubElement(seg, "Connection", **{k: v for k, v in (("FromID", frm), ("ToID", to)) if v})
        _dexpi_set(seg, segment_dexpi(s0))
        stream_sets(seg, s0)
        for extra in chain[1:]: stream_sets(seg, extra, "." + extra.id)
    if covered != set(fs.streams): raise ValueError(f"streams not exported: {sorted(set(fs.streams) - covered)}")
    ET.indent(root)
    xml = ET.tostring(root, encoding="unicode", xml_declaration=False)
    out = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml + "\n"
    if path:
        with open(path, "w", encoding="utf-8") as f: f.write(out)
    return out


DEXPI_UNIT_PARAMS = {"DifferentialPressure": "DifferentialPressure_kPa", "DesignVolumeFlowRate": "DesignVolumeFlowRate_m3_h",
                     "DesignHeatFlowRate": "DesignHeatFlowRate_kW"}


def _to_celsius(v: float, units: str) -> float:
    return {"DegreeCelsius": v, "Kelvin": v - 273.15, "DegreeFahrenheit": (v - 32) * 5 / 9}[units]


def _attrs(el: ET.Element, set_name: str) -> dict[str, tuple[str, str]]:
    out = {}
    for g in el.findall("GenericAttributes"):
        if g.get("Set") == set_name:
            for a in g.findall("GenericAttribute"): out[a.get("Name")] = (a.get("Value"), a.get("Units", ""))
    return out


def _fill(st: Stream, data: dict, checks: dict):
    for f, name, _ in STREAM_FIELDS:
        if name in data: setattr(st, f, float(data[name][0]))
    st.composition = {k[2:-1]: float(v) for k, (v, _) in data.items() if k.startswith("x[")}
    st.checks = {k: float(v) for k, (v, _) in checks.items()}


def load(path_or_xml: str) -> Flowsheet:
    """Read back a file produced by export() (and simple Proteus files with the same structure)."""
    root = ET.fromstring(path_or_xml) if path_or_xml.lstrip().startswith("<") else ET.parse(path_or_xml).getroot()
    if root.tag != "PlantModel": raise ValueError(f"root element is {root.tag!r}, expected PlantModel")
    info = root.find("PlantInformation")
    fs = Flowsheet(name=info.get("Name", "case") if info is not None else "case")
    owner: dict[str, str] = {}                                       # nozzle / piping-component id -> unit tag
    for eq in root.findall("Equipment"):
        tag = eq.get("TagName") or eq.get("ID")
        ir = _attrs(eq, "HysysBridge").get("IRType", (None,))[0] or REV_CLASS.get(eq.get("ComponentClass"), "unknown")
        params = {k: float(v) for k, (v, _) in _attrs(eq, "Parameters").items()}
        for k, (v, units) in _attrs(eq, "DexpiAttributes").items():          # DEXPI design attributes -> params
            if k in DEXPI_UNIT_PARAMS: params[DEXPI_UNIT_PARAMS[k]] = float(v)
        fs.units[tag] = Unit(id=tag, type=ir, params=params)
        for n in eq.findall("Nozzle"): owner[n.get("ID")] = tag
    comps_of: dict[int, list[ET.Element]] = {}
    for seg in root.iter("PipingNetworkSegment"):                    # valves / tees written by export()
        mine = [pc for pc in seg.findall("PipingComponent") if "IRType" in _attrs(pc, "HysysBridge")]
        comps_of[id(seg)] = mine
        for pc in mine:
            tag = pc.get("TagName") or pc.get("ID")
            fs.units[tag] = Unit(id=tag, type=_attrs(pc, "HysysBridge")["IRType"][0]); owner[pc.get("ID")] = tag
    for seg in root.iter("PipingNetworkSegment"):
        con = seg.find("Connection")
        if con is None: raise ValueError(f"segment {seg.get('ID')} has no Connection")
        sid = seg.get("TagName") or seg.get("ID")
        for end in ("FromID", "ToID"):
            ref = con.get(end)
            if ref is not None and ref not in owner:
                raise ValueError(f"segment {sid}: {end}={ref!r} is not a known nozzle")
        comps = comps_of[id(seg)]
        ids = [sid] + [_attrs(pc, "HysysBridge")["OutStream"][0] for pc in comps]
        tags = [pc.get("TagName") or pc.get("ID") for pc in comps]
        for k, stream_id in enumerate(ids):
            st = Stream(id=stream_id)
            st.src = owner.get(con.get("FromID")) if k == 0 else tags[k - 1]
            st.dst = tags[k] if k < len(tags) else owner.get(con.get("ToID"))
            suffix = "" if k == 0 else "." + stream_id
            data = _attrs(seg, "StreamData" + suffix)
            _fill(st, data, _attrs(seg, "HMBChecks" + suffix))
            dx = _attrs(seg, "DexpiAttributes")
            if k == 0 and "T_C" not in data and "Temperature" not in data and "OperatingTemperature" in dx:   # DEXPI-only file
                st.T_C = _to_celsius(float(dx["OperatingTemperature"][0]), dx["OperatingTemperature"][1])
            st.kind = "feed" if st.src is None else ("product" if st.dst is None else "intermediate")
            fs.streams[stream_id] = st
    fs.components = sorted({c for s in fs.streams.values() for c in s.composition})
    fs.relink()
    return fs
