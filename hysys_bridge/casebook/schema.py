"""Case record: one JSON file per published case. Rules (see docs/PAPER_TO_SIMULATION_ARCHITECTURE.md, sections 1 and 3):
every number carries either an `anchor` (where in the source it comes from) or an `assumed` reason; pressure basis and composition basis are
mandatory; reconstructed values say how they were checked; a case is only `verified` after a human reviewed it. Facts only: no source text or tables.
JSON, not YAML, so the package has no dependency."""
from __future__ import annotations
import copy, hashlib, json
from ..ir import Flowsheet, Stream, Unit

ATM_KPA = 101.325
STATUS = {"draft", "reviewed", "built", "verified", "blocked", "unresolved"}
NEEDS_REVIEW = {"reviewed", "built", "verified"}
READ = {"full-text", "abstract-only", "snippet-only", "computed"}      # computed: the reference is an independent calculation, not a document
UNIT_TYPES = {"mixer", "splitter", "pump", "heater", "cooler", "valve", "compressor", "separator", "column", "reactor", "exchanger", "recycle", "conversion_reactor"}
SPEC_BY_OUTLET = {"heater", "cooler", "pump", "valve", "compressor"}      # units whose outlet stream carries the published specification, so T and P are required there
KINDS = {"unit_duty": "kJ/h", "stream_T_C": "C", "stream_P_kPa": "kPa", "stream_mass_kg_h": "kg/h", "stream_vapor_fraction": "-", "stream_mass_fraction": "-", "streams_mass_sum_kg_h": "kg/h", "units_duty_sum_kJ_h": "kJ/h"}
REACTION_PHASES = {"Vapor", "Liquid", "Mixture"}
THERMAL_MODES = {"isothermal": "Isothermic", "adiabatic": "Adiabatic"}      # case word -> DWSIM ReactorOperationMode (verified 2026-11-21)
TOP = ("id", "source", "basis", "streams", "units", "reported", "tolerance", "status")


def load(path: str) -> dict:
    with open(path) as f: return json.load(f)


def case_hash(case: dict) -> str:
    return hashlib.sha256(json.dumps(case, sort_keys=True).encode()).hexdigest()[:12]


def _qty(path, q, units, problems, need_anchor=True):
    if not isinstance(q, dict) or not isinstance(q.get("value"), (int, float)) or isinstance(q.get("value"), bool):
        problems.append(f"{path}: needs a numeric value"); return
    if q.get("unit") not in units: problems.append(f"{path}: unit {q.get('unit')!r} must be one of {sorted(units)}")
    if need_anchor and not (q.get("anchor") or q.get("assumed")): problems.append(f"{path}: needs an anchor (where in the source) or an assumed reason")

def _reaction_problems(pa, params, basis) -> list[str]:
    """A conversion reactor carries one reaction: stoichiometry (reactants negative), base compound, conversion in percent, phase, thermal mode.
    The stoichiometry must conserve mass with the case's own molar masses: a typo in a coefficient is caught before any simulator runs."""
    p, r = [], params.get("reaction")
    if not isinstance(r, dict): return [f"{pa}.params.reaction is required on a conversion_reactor"]
    st, comps, mm = r.get("stoichiometry"), basis.get("compounds", []), basis.get("molar_mass_g_mol", {})
    if not (isinstance(st, dict) and st and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0 for v in st.values())): return p + [f"{pa}.params.reaction.stoichiometry must be {{compound: nonzero number}}"]
    if set(st) - set(comps): p.append(f"{pa}.params.reaction.stoichiometry has compounds not in basis.compounds: {sorted(set(st) - set(comps))}")
    if not (any(v < 0 for v in st.values()) and any(v > 0 for v in st.values())): p.append(f"{pa}.params.reaction needs reactants (negative) and products (positive)")
    if r.get("base_compound") not in st or st.get(r.get("base_compound"), 0) >= 0: p.append(f"{pa}.params.reaction.base_compound must be a reactant in the stoichiometry")
    cv = r.get("conversion_pct")
    if not (isinstance(cv, (int, float)) and not isinstance(cv, bool) and 0 < cv <= 100): p.append(f"{pa}.params.reaction.conversion_pct must be in (0, 100]")
    if r.get("phase") not in REACTION_PHASES: p.append(f"{pa}.params.reaction.phase must be one of {sorted(REACTION_PHASES)}")
    if params.get("thermal_mode") not in THERMAL_MODES: p.append(f"{pa}.params.thermal_mode must be one of {sorted(THERMAL_MODES)}")
    if not (r.get("anchor") or r.get("assumed")): p.append(f"{pa}.params.reaction needs an anchor (where in the source) or an assumed reason")
    if set(st) <= set(mm):
        net, scale = sum(v * mm[k] for k, v in st.items()), sum(abs(v) * mm[k] for k, v in st.items())
        if abs(net) > 1e-3 * scale: p.append(f"{pa}.params.reaction does not conserve mass: net {net:.4f} g per reaction with the case's molar masses")
    else: p.append(f"{pa}.params.reaction needs basis.molar_mass_g_mol for every compound in it, to check the mass balance")
    return p



def validate(case: dict) -> list[str]:
    """Returns a list of problems; empty means the record is well-formed (not that its numbers are right)."""
    p: list[str] = []
    for k in TOP:
        if k not in case: p.append(f"missing {k!r}")
    if p: return p
    src = case["source"]
    for k in ("title", "licence", "use", "read", "fetch_route"):
        if not src.get(k): p.append(f"source.{k} is required")
    if not (src.get("doi") or src.get("url")): p.append("source needs a doi or a url")
    if src.get("read") not in READ: p.append(f"source.read must be one of {sorted(READ)}")
    b = case["basis"]
    for k in ("compounds", "package_in_paper", "packages", "composition_basis"):
        if not b.get(k): p.append(f"basis.{k} is required")
    comps = b.get("compounds", [])
    if b.get("composition_basis") == "mole" and set(b.get("molar_mass_g_mol", {})) != set(comps):
        p.append("mole-basis compositions need basis.molar_mass_g_mol for every compound (DWSIM takes mass fractions)")
    if case["status"] not in STATUS: p.append(f"status must be one of {sorted(STATUS)}")
    rv = case.get("review") or {}
    if case["status"] in NEEDS_REVIEW and not rv.get("method"): p.append("a reviewed/built/verified case needs review.method (the checks applied)")
    if case["status"] == "verified" and not rv.get("human"): p.append("verified needs review.human = true (a person signed the numbers off)")
    units = {}
    for i, u in enumerate(case["units"]):
        if u.get("type") not in UNIT_TYPES: p.append(f"units[{i}].type {u.get('type')!r} unknown")
        if not u.get("id") or u["id"] in units: p.append(f"units[{i}].id missing or duplicated")
        sr = u.get("params", {}).get("split_ratio")
        if sr is not None and not (u.get("type") == "splitter" and isinstance(sr, (int, float)) and 0 <= sr <= 1): p.append(f"units[{i}].params.split_ratio must be 0..1 and only on a splitter")
        units[u.get("id")] = u
        if u.get("type") == "conversion_reactor": p += _reaction_problems(f"units[{i}]", u.get("params", {}), case["basis"])
        elif "reaction" in u.get("params", {}): p.append(f"units[{i}].params.reaction belongs on a conversion_reactor only")
    if sum(u.get("type") == "conversion_reactor" for u in case["units"]) > 1: p.append("at most one conversion_reactor per case: every reactor would share DWSIM's DefaultSet and so every reaction")
    ids = set()
    for i, s in enumerate(case["streams"]):
        pa = f"streams[{s.get('id', i)}]"
        if not s.get("id") or s["id"] in ids: p.append(f"{pa}: id missing or duplicated")
        ids.add(s.get("id"))
        role = s.get("role")
        if role not in ("feed", "intermediate", "product"): p.append(f"{pa}.role must be feed, intermediate or product")
        if (role == "feed") != (s.get("src") is None): p.append(f"{pa}: a feed has no src, every other stream has one")
        if role == "product" and s.get("dst") is not None: p.append(f"{pa}: a product has no dst")
        for e in ("src", "dst"):
            if s.get(e) is not None and s[e] not in units: p.append(f"{pa}.{e} {s[e]!r} is not a unit")
        needs_tp = role == "feed" or units.get(s.get("src"), {}).get("type") in SPEC_BY_OUTLET     # other streams are computed: T and P optional, checked when given
        pr = s.get("P")
        if needs_tp or "T" in s: _qty(pa + ".T", s.get("T"), {"C"}, p)
        if needs_tp or "P" in s: _qty(pa + ".P", pr, {"bar", "kPa"}, p)
        if isinstance(pr, dict) and pr.get("basis") not in ("absolute", "gauge"): p.append(f"{pa}.P.basis must be absolute or gauge (it has caused mismatches before)")
        if role == "feed":
            _qty(pa + ".mass_flow", s.get("mass_flow"), {"kg/h"}, p)
            c = s.get("composition") or {}; v = c.get("values") or {}
            if set(v) - set(comps): p.append(f"{pa}.composition has compounds not in basis.compounds: {sorted(set(v) - set(comps))}")
            if abs(sum(v.values()) - 1.0) > 1e-6: p.append(f"{pa}.composition sums to {sum(v.values()):.6f}, not 1")
            for k, how in (c.get("provenance") or {}).items():
                if how not in ("reported", "assumed", "reconstructed"): p.append(f"{pa}.composition.provenance[{k}] must be reported, assumed or reconstructed")
            if set(v) - set(c.get("provenance") or {}): p.append(f"{pa}.composition.provenance must cover every compound")
            if "reconstructed" in (c.get("provenance") or {}).values() and not c.get("check"): p.append(f"{pa}.composition is reconstructed: say in composition.check how it was confirmed")
    for uid, u in units.items():                                # a separator's outlets are connected in file order: port 0 = vapour, port 1 = liquid (verified on the DWSIM Vessel, 2026-11-20)
        if u.get("type") not in ("separator", "conversion_reactor"): continue
        outs = [x for x in case["streams"] if x.get("src") == uid]
        ph = [x.get("phase") for x in outs]
        if ph != ["vapor", "liquid"]: p.append(f"unit {uid}: a separator or conversion reactor needs exactly two outlet streams with phase 'vapor' then 'liquid' in that file order, got {ph}")
    names = set()
    for i, r in enumerate(case["reported"]):
        pa = f"reported[{r.get('name', i)}]"
        if not r.get("name") or r["name"] in names: p.append(f"{pa}: name missing or duplicated")
        names.add(r.get("name"))
        if r.get("kind") not in KINDS: p.append(f"{pa}.kind must be one of {sorted(KINDS)}"); continue
        if "range" in r:                                        # a published range ("0.4 - 0.8") instead of a point value
            rg = r["range"]
            if not (isinstance(rg, list) and len(rg) == 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in rg) and rg[0] <= rg[1]): p.append(f"{pa}.range must be [low, high] numbers with low <= high")
            if r.get("unit") != KINDS[r["kind"]]: p.append(f"{pa}: unit {r.get('unit')!r} must be one of {[KINDS[r['kind']]]}")
            if not (r.get("anchor") or r.get("assumed")): p.append(f"{pa}: needs an anchor (where in the source) or an assumed reason")
        else: _qty(pa, r, {KINDS[r["kind"]]}, p)
        if "pass_rel" in r and not (isinstance(r["pass_rel"], (int, float)) and 0 < r["pass_rel"] <= 1): p.append(f"{pa}.pass_rel must be in (0, 1]")
        if r["kind"] == "unit_duty":
            if r.get("target") not in units: p.append(f"{pa}.target must be a unit id")
        elif r["kind"] == "units_duty_sum_kJ_h":
            if not (isinstance(r.get("targets"), list) and r["targets"] and set(r["targets"]) <= set(units)): p.append(f"{pa}.targets must be a non-empty list of unit ids")
        elif r["kind"] == "streams_mass_sum_kg_h":
            if not (isinstance(r.get("targets"), list) and r["targets"] and set(r["targets"]) <= ids): p.append(f"{pa}.targets must be a non-empty list of stream ids")
        elif r.get("target") not in ids: p.append(f"{pa}.target must be a stream id")
        if r["kind"] == "stream_mass_fraction" and r.get("compound") not in comps: p.append(f"{pa}.compound must be one of the case's compounds")
    if not case["reported"]: p.append("reported is empty: a case without a published result to compare against is not a reference case")
    base_problems = validate({**case, "scenarios": [], "reproduce": None}) if case.get("scenarios") else []   # a scenario reports only the problems it adds, not the base case's again
    ssc = set()
    for i, sc in enumerate(case.get("scenarios", [])):
        pa = f"scenarios[{sc.get('id', i)}]"
        if not sc.get("id") or sc["id"] in ssc or sc["id"] == "base": p.append(f"{pa}: id missing, duplicated or 'base' (the unmodified case is always scenario base)")
        ssc.add(sc.get("id"))
        if not sc.get("why"): p.append(f"{pa}.why is required: a scenario varies something inside a stated uncertainty, not to fit the answer")
        if not sc.get("overrides"): p.append(f"{pa}.overrides is empty")
        if not isinstance(sc.get("drop_reported", []), list): p.append(f"{pa}.drop_reported must be a list of reported names")
        else:
            try: sub = apply_scenario(case, sc["id"]); p += [f"{pa}: {x}" for x in validate({**sub, "scenarios": [], "reproduce": None}) if x not in base_problems]
            except (KeyError, IndexError, TypeError) as e: p.append(f"{pa}: an override path does not exist ({e!r})")
    rp = case.get("reproduce")
    if rp is not None and not (isinstance(rp.get("expected"), dict) and set(rp["expected"]) <= set(b.get("packages", [])) and isinstance(rp.get("rel_tol"), (int, float)) and rp.get("source")):
        p.append("reproduce needs expected {package: value} for listed packages, rel_tol and source (where the earlier numbers came from)")
    t = case["tolerance"]
    if not (isinstance(t.get("pass_rel"), (int, float)) and 0 < t["pass_rel"] <= 1): p.append("tolerance.pass_rel must be in (0, 1]")
    return p


def capability(case: dict) -> dict:
    """Unit types vs what the DWSIM backend has verified (hysys_bridge/dwsim/backend.py)."""
    from ..dwsim.backend import UNIT_PARAMS_VERIFIED
    missing = sorted({u["type"] for u in case["units"]} - UNIT_PARAMS_VERIFIED)
    return {"buildable": not missing, "unverified_unit_types": missing}


def _bar_to_kpa(q: dict) -> float:
    v = q["value"] * (100.0 if q["unit"] == "bar" else 1.0)
    return v + ATM_KPA if q.get("basis") == "gauge" else v


def apply_scenario(case: dict, scenario_id: str) -> dict:
    """A copy of the case with the scenario's overrides applied. Override: {stream | unit | reported: id, path: [keys...], set: value}; the result must still validate."""
    if scenario_id == "base": return copy.deepcopy(case)
    sc = next((x for x in case.get("scenarios", []) if x["id"] == scenario_id), None)
    if sc is None: raise KeyError(f"no scenario {scenario_id!r}")
    c = copy.deepcopy(case)
    for o in sc["overrides"]:
        kind, key, where = (("unit", o["unit"], c["units"]) if "unit" in o else ("reported", o["reported"], c["reported"]) if "reported" in o else ("stream", o["stream"], c["streams"]))
        node = next((x for x in where if x.get("id", x.get("name")) == key), None)
        if node is None: raise KeyError(f"no {kind} {key!r} to override")
        for k in o["path"][:-1]: node = node[k]
        if o["path"][-1] not in node: raise KeyError(o["path"][-1])
        node[o["path"][-1]] = o["set"]
    drop = set(sc.get("drop_reported", []))                                  # expectations that do not apply in this scenario (e.g. compositions of an empty stream)
    if drop - {r["name"] for r in c["reported"]}: raise KeyError(f"drop_reported names unknown reported values: {sorted(drop - {r['name'] for r in c['reported']})}")
    c["reported"] = [r for r in c["reported"] if r["name"] not in drop]
    c["scenarios"] = []                                                      # already applied: re-validating the result must not apply them again
    return c


def to_flowsheet(case: dict, package: str) -> Flowsheet:
    """Case record to the Flowsheet IR the DWSIM writer takes: pressures absolute in kPa, compositions as mass fractions."""
    probs = validate(case)
    if probs: raise ValueError("case is not valid: " + "; ".join(probs))
    mm = case["basis"].get("molar_mass_g_mol", {})
    fs = Flowsheet(case["id"], package, list(case["basis"]["compounds"]))
    for u in case["units"]: fs.units[u["id"]] = Unit(u["id"], u["type"], dict(u.get("params", {})))
    for s in case["streams"]:
        st = Stream(s["id"], s["role"], s.get("src"), s.get("dst"), T_C=s["T"]["value"] if "T" in s else None, P_kPa=_bar_to_kpa(s["P"]) if "P" in s else None)
        if s["role"] == "feed":
            st.mass_flow_kg_h = s["mass_flow"]["value"]; v = s["composition"]["values"]
            if case["basis"]["composition_basis"] == "mole":
                m = {k: x * mm[k] for k, x in v.items()}; tot = sum(m.values()); v = {k: x / tot for k, x in m.items()}
            st.composition, st.composition_basis = v, "mass"
        fs.streams[s["id"]] = st
    fs.relink(); return fs
