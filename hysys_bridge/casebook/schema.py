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
READ = {"full-text", "abstract-only", "snippet-only"}
UNIT_TYPES = {"mixer", "splitter", "pump", "heater", "cooler", "valve", "compressor", "separator", "column", "reactor", "exchanger"}
KINDS = {"unit_duty": "kJ/h", "stream_T_C": "C", "stream_P_kPa": "kPa"}
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
        units[u.get("id")] = u
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
        _qty(pa + ".T", s.get("T"), {"C"}, p)
        pr = s.get("P")
        _qty(pa + ".P", pr, {"bar", "kPa"}, p)
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
    names = set()
    for i, r in enumerate(case["reported"]):
        pa = f"reported[{r.get('name', i)}]"
        if not r.get("name") or r["name"] in names: p.append(f"{pa}: name missing or duplicated")
        names.add(r.get("name"))
        if r.get("kind") not in KINDS: p.append(f"{pa}.kind must be one of {sorted(KINDS)}"); continue
        _qty(pa, r, {KINDS[r["kind"]]}, p)
        if r["kind"] == "unit_duty" and r.get("target") not in units: p.append(f"{pa}.target must be a unit id")
        if r["kind"] != "unit_duty" and r.get("target") not in ids: p.append(f"{pa}.target must be a stream id")
    if not case["reported"]: p.append("reported is empty: a case without a published result to compare against is not a reference case")
    ssc = set()
    for i, sc in enumerate(case.get("scenarios", [])):
        pa = f"scenarios[{sc.get('id', i)}]"
        if not sc.get("id") or sc["id"] in ssc or sc["id"] == "base": p.append(f"{pa}: id missing, duplicated or 'base' (the unmodified case is always scenario base)")
        ssc.add(sc.get("id"))
        if not sc.get("why"): p.append(f"{pa}.why is required: a scenario varies something inside a stated uncertainty, not to fit the answer")
        if not sc.get("overrides"): p.append(f"{pa}.overrides is empty")
        else:
            try: sub = apply_scenario(case, sc["id"], _check=False); p += [f"{pa}: {x}" for x in validate({**sub, "scenarios": []})]
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


def apply_scenario(case: dict, scenario_id: str, _check: bool = True) -> dict:
    """A copy of the case with the scenario's overrides applied. Override: {stream, path: [keys...], set: value}; the result must still validate."""
    if scenario_id == "base": return copy.deepcopy(case)
    sc = next((x for x in case.get("scenarios", []) if x["id"] == scenario_id), None)
    if sc is None: raise KeyError(f"no scenario {scenario_id!r}")
    c = copy.deepcopy(case)
    for o in sc["overrides"]:
        node = next(x for x in c["streams"] if x["id"] == o["stream"])
        for k in o["path"][:-1]: node = node[k]
        if o["path"][-1] not in node: raise KeyError(o["path"][-1])
        node[o["path"][-1]] = o["set"]
    return c


def to_flowsheet(case: dict, package: str) -> Flowsheet:
    """Case record to the Flowsheet IR the DWSIM writer takes: pressures absolute in kPa, compositions as mass fractions."""
    probs = validate(case)
    if probs: raise ValueError("case is not valid: " + "; ".join(probs))
    mm = case["basis"].get("molar_mass_g_mol", {})
    fs = Flowsheet(case["id"], package, list(case["basis"]["compounds"]))
    for u in case["units"]: fs.units[u["id"]] = Unit(u["id"], u["type"], dict(u.get("params", {})))
    for s in case["streams"]:
        st = Stream(s["id"], s["role"], s.get("src"), s.get("dst"), T_C=s["T"]["value"], P_kPa=_bar_to_kpa(s["P"]))
        if s["role"] == "feed":
            st.mass_flow_kg_h = s["mass_flow"]["value"]; v = s["composition"]["values"]
            if case["basis"]["composition_basis"] == "mole":
                m = {k: x * mm[k] for k, x in v.items()}; tot = sum(m.values()); v = {k: x / tot for k, x in m.items()}
            st.composition, st.composition_basis = v, "mass"
        fs.streams[s["id"]] = st
    fs.relink(); return fs
