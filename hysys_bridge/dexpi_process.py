"""Flowsheet IR -> DEXPI *Process* model (pyDEXPI ProcessModel), saved with pyDEXPI's JSON serializer.

The Proteus P&ID XML (dexpi_export.py) has no place for stream pressure, flows or composition. DEXPI keeps
those in the Process model: ProcessStep (one per unit), MaterialPort, Stream (a ProcessConnection with
temperature / pressure / massFlow / volumeFlow), MaterialTemplate (component list), MaterialState ->
MaterialStateType -> Composition (mole or mass fractions, in template-component order).

Needs the optional dependency  pip install pydexpi  (imported lazily; tested with 2.1.0).
Diagram boundaries: DEXPI streams require a source and a target Port, so each feed/product gets a boundary
ProcessStep named BOUNDARY-<stream> (battery limit), which read_streams() maps back to an open end.

Not exported (no DEXPI process attribute I could verify): vapour fraction and the other H&MB check values
(except specific enthalpy = H/m when both are present). Units: degC, kPa (absolute), kg/h, m3/h, kJ/kg.
"""
from __future__ import annotations
import datetime
from .ir import Flowsheet, Stream

BOUNDARY = "BOUNDARY-"
# IR unit type -> DEXPI ProcessStep subclass. Readers such as dwsim-dexpi pick the equipment category from the step's
# CLASS (a plain ProcessStep comes out as "Generic"); Source/Sink mark where a line enters/leaves the diagram.
STEP_CLASS = {"pump": "Pumping", "compressor": "Compressing", "heater": "SupplyingThermalEnergy",
              "cooler": "RemovingThermalEnergy", "separator": "SeparatingByPhaseSeparation", "column": "Distilling",
              "reactor": "ReactingChemicals", "valve": "RegulatingFlow", "mixer": "Mixing", "splitter": "SplittingMaterial"}
# a few step classes have a mandatory `method`; use the neutral member (nothing in the IR says more)
STEP_METHOD = {"Compressing": ("CompressionMethod", "Unspecified"), "RemovingThermalEnergy": ("HeatExchangeMethod", "Generic"),
               "ReactingChemicals": ("ReactionProcessType", "Unspecified")}


def _pydexpi():
    try:
        import pydexpi.pydexpi_classes.pydexpi_classes as C
        from pydexpi.loaders.json_serializer import JsonSerializer
    except ImportError as e:
        raise SystemExit("dexpi_process needs pydexpi:  pip install pydexpi") from e
    return C, JsonSerializer


def _qv(C, value: float, unit_enum, unit_name: str, case: str = "design"):
    return C.QualifiedValue(case=case, value=C.PhysicalQuantity(value=float(value), unit=unit_enum(unit_name)))


def _mls(C, text: str):
    return C.MultiLanguageString(singleLanguageStrings=[C.SingleLanguageString(language="en", value=text)])


def build(fs: Flowsheet):
    """Return a pyDEXPI EngineeringModel whose conceptualModel is a ProcessModel."""
    C, _ = _pydexpi()
    fs.relink()
    comps = list(fs.components) or sorted({c for s in fs.streams.values() for c in s.composition})
    mats = [C.PureMaterialComponent(identifier=c, label=c) for c in comps]
    lom = C.ListOfMaterialComponents(component=mats)
    mt = C.MaterialTemplate(listOfComponents=lom, identifier="MT-1", label="components", numberOfMaterialComponents=len(comps),
                            numberOfPhases=1, description=_mls(C, "component list of the flowsheet"))
    steps: dict[str, object] = {}
    ports: dict[tuple[str, str, str], object] = {}                       # (step, stream, 'in'|'out') -> Port
    def step(name, label=None, cls_name=None):
        if name not in steps:
            extra = {}
            if cls_name in STEP_METHOD: extra["method"] = getattr(C, STEP_METHOD[cls_name][0])(STEP_METHOD[cls_name][1])
            steps[name] = getattr(C, cls_name or "ProcessStep")(identifier=name, label=label or name, ports=[], **extra)
        return steps[name]
    def port(stepname, sid, d):
        key = (stepname, sid, d)
        if key not in ports:
            # Port.connectorReference and Stream.source/target are mandatory references to each other (a cycle by
            # design in DEXPI), so the port is built unvalidated and linked to its stream right after the stream exists.
            p = C.MaterialPort.model_construct(identifier=f"{stepname}:{sid}:{d}", materialTemplateReference=mt,
                                               nominalDirection=C.PortDirection("Inlet" if d == "in" else "Outlet"))
            ports[key] = p; step(stepname).ports.append(p)
        return ports[key]
    for uid, u in fs.units.items(): step(uid, cls_name=STEP_CLASS.get(u.type))
    streams, states = [], []
    for sid, s in fs.streams.items():
        src = s.src or f"{BOUNDARY}{sid}"; dst = s.dst or f"{BOUNDARY}{sid}"
        if s.src is None: step(src, f"{sid} (feed)", "Source")
        if s.dst is None: step(dst, f"{sid} (product)", "Sink")
        kw = {}
        if s.T_C is not None: kw["temperature"] = [_qv(C, s.T_C, C.TemperatureUnit, "DegreeCelsius")]
        if s.P_kPa is not None: kw["pressure"] = [_qv(C, s.P_kPa, C.PressureAbsoluteUnit, "Kilopascal")]
        if s.mass_flow_kg_h is not None: kw["massFlow"] = [_qv(C, s.mass_flow_kg_h, C.MassFlowRateUnit, "KilogramPerHour")]
        if s.vol_flow_m3_h is not None: kw["volumeFlow"] = [_qv(C, s.vol_flow_m3_h, C.VolumeFlowRateUnit, "MetreCubedPerHour")]
        h = s.checks.get("enthalpy_kJ_h")
        if s.composition or (h is not None and s.mass_flow_kg_h):
            mkw = {}
            if s.composition:
                # DEXPI carries a composition as ONE vector quantity in template-component order (readers expect this form)
                vec = C.PhysicalQuantityVector(values=[float(s.composition.get(c, 0.0)) for c in comps], unit=C.RatioUnit("Fraction"))
                fr = [C.QualifiedValue(case="design", value=vec)]
                mkw["composition"] = C.Composition(massFractions=fr) if s.composition_basis == "mass" else C.Composition(moleFractions=fr)
            if h is not None and s.mass_flow_kg_h:            # H&MB total enthalpy flow -> specific enthalpy
                mkw["specificEnthalpy"] = [_qv(C, h / s.mass_flow_kg_h, C.MassSpecificEnergyUnit, "KilojoulePerKilogram")]
            mst = C.MaterialStateType(identifier=f"MST-{sid}", label=sid, description=_mls(C, f"single-phase state of stream {sid}"), **mkw)
            ms = C.MaterialState(phases=[mst], state=mst, identifier=f"MS-{sid}", label=sid, description=f"state of stream {sid}")
            states.append(ms); kw["materialStateReference"] = ms
        p_src, p_dst = port(src, sid, "out"), port(dst, sid, "in")
        st = C.Stream(identifier=sid, label=sid, source=p_src, target=p_dst, materialTemplateReference=mt, **kw)
        p_src.connectorReference = p_dst.connectorReference = st
        streams.append(st)
    pm = C.ProcessModel(processSteps=list(steps.values()), processConnections=streams, materialTemplates=[mt],
                        materialComponents=mats, listsOfMaterialComponents=[lom], materialStates=states)
    return C.EngineeringModel(conceptualModel=pm, originatingSystemName="hysys_bridge", originatingSystemVersion="0.1",
                              exportDateTime=datetime.datetime.now(datetime.timezone.utc))


def export_json(fs: Flowsheet, dir_path, filename: str):
    _, J = _pydexpi()
    model = build(fs)
    J().save(model, dir_path, filename)
    return model


def read_streams(dir_path, filename: str) -> dict[str, dict]:
    """Read a saved process model back: {stream id: {src, dst, T_C, P_kPa, mass_flow_kg_h, vol_flow_m3_h,
    composition, basis}} (src/dst None at a diagram boundary)."""
    C, J = _pydexpi()
    em = J().load(dir_path, filename)
    pm = em.conceptualModel
    step_of = {p.id: st.identifier for st in pm.processSteps for p in (st.ports or [])}
    steps_by_name = {st.identifier: st for st in pm.processSteps}
    comps = [m.identifier for m in (pm.materialTemplates[0].listOfComponents.component if pm.materialTemplates else [])]
    val = lambda lst: lst[0].value.value if lst else None
    out = {}
    for s in pm.processConnections:
        if not isinstance(s, C.Stream): continue
        a, b = step_of.get(s.source.id), step_of.get(s.target.id)
        is_edge = lambda name: name is None or name.startswith(BOUNDARY) or isinstance(steps_by_name.get(name), (C.Source, C.Sink))
        d = {"src": None if is_edge(a) else a, "dst": None if is_edge(b) else b,
             "T_C": val(s.temperature), "P_kPa": val(s.pressure), "mass_flow_kg_h": val(s.massFlow),
             "vol_flow_m3_h": val(s.volumeFlow), "composition": {}, "basis": None}
        ms = s.materialStateReference
        mst = (ms.state or (ms.phases[0] if ms.phases else None)) if ms is not None else None
        if mst is not None:
            comp = mst.composition
            if comp is not None:
                fr, d["basis"] = (comp.massFractions, "mass") if comp.massFractions else (comp.moleFractions, "mole")
                if len(fr) == 1 and hasattr(fr[0].value, "values"):          # vector form (DEXPI-standard)
                    d["composition"] = {c: x for c, x in zip(comps, fr[0].value.values) if x}
                else:                                                        # one quantity per component (older files of ours)
                    d["composition"] = {c: q.value for c, q in zip(comps, fr) if q.value}
            d["specific_enthalpy_kJ_kg"] = val(mst.specificEnthalpy)
        out[s.identifier] = d
    return out
