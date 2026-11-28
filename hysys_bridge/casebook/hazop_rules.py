"""The HAZOP cause and safeguard rules store (studies/hazop_rules/rules.json): candidate causes per guide word and parameter, safeguard types, worked examples and method
notes, each with the source it came from and how that source was read. Rules of the store: an entry exists only if a source that was read gives it (nothing from memory);
every entry is a candidate for the study team and is marked unreviewed; suggestions are returned beside the team's own causes and safeguards and never replace them."""
from __future__ import annotations
import json, os

PATH = os.path.join(os.path.dirname(__file__), "..", "..", "studies", "hazop_rules", "rules.json")
GUIDE_WORDS = {"NONE", "MORE", "LESS", "REVERSE", "AS_WELL_AS", "PART_OF", "OTHER_THAN"}
EQUIPMENT = {"valve", "pump", "controller", "heater", "exchanger", "line", "process"}
OTHER_THAN_COVERS = {"AS_WELL_AS", "PART_OF"}          # the source's 'other composition than usual' causes are offered for both composition guide words (my mapping, stated in the worksheet)


def load(path: str | None = None) -> dict:
    with open(path or PATH) as f: return json.load(f)


def validate(store: dict) -> list[str]:
    p, src = [], {s.get("id"): s for s in store.get("sources", [])}
    for s in store.get("sources", []):
        for k in ("id", "title", "url", "licence", "how_read", "read"):
            if not s.get(k): p.append(f"source {s.get('id', '?')}: {k} is required")
    ids = set()
    def common(kind, e):
        i = e.get("id", "?")
        if not e.get("id") or e["id"] in ids: p.append(f"{kind} {i}: id missing or duplicated")
        ids.add(e.get("id"))
        if not e.get("sources") or set(e["sources"]) - set(src): p.append(f"{kind} {i}: sources must name read sources from the store's source list")
    for e in store.get("causes", []):
        common("cause", e)
        if not (isinstance(e.get("text"), str) and e["text"].strip()): p.append(f"cause {e.get('id')}: text is required")
        if e.get("guide_word") not in GUIDE_WORDS: p.append(f"cause {e.get('id')}: unknown guide word {e.get('guide_word')!r}")
        if not e.get("parameter"): p.append(f"cause {e.get('id')}: parameter is required")
        if e.get("equipment") not in EQUIPMENT: p.append(f"cause {e.get('id')}: equipment must be one of {sorted(EQUIPMENT)}")
        if e.get("status") != "candidate-unreviewed": p.append(f"cause {e.get('id')}: status must be candidate-unreviewed (a store entry is a suggestion, never a finding)")
    for e in store.get("safeguard_types", []):
        common("safeguard type", e)
        if not (isinstance(e.get("text"), str) and e["text"].strip()) or e.get("status") != "candidate-unreviewed": p.append(f"safeguard type {e.get('id')}: needs text and status candidate-unreviewed")
    for e in store.get("worked_examples", []):
        common("worked example", e)
        for k in ("context", "parameter", "guide_word", "consequence"):
            if not e.get(k): p.append(f"worked example {e.get('id')}: {k} is required")
        for k in ("causes", "responses_in_source"):
            if not (isinstance(e.get(k), list) and e[k] and all(isinstance(x, str) and x for x in e[k])): p.append(f"worked example {e.get('id')}: {k} must be a non-empty list of strings")
    for e in store.get("method_notes", []):
        common("method note", e)
        if not e.get("text"): p.append(f"method note {e.get('id')}: text is required")
    return p


def suggest(store: dict, parameter: str, guide_word: str, upstream_equipment: list[str] | None = None) -> dict:
    """Candidates for one deviation. upstream_equipment (the team's list of equipment upstream of the feed) limits the causes to those equipment tags plus 'line' and 'process'."""
    keep = None if upstream_equipment is None else set(upstream_equipment) | {"line", "process"}
    gws = {guide_word} | ({"OTHER_THAN"} if parameter == "composition" and guide_word in OTHER_THAN_COVERS else set())
    causes = [{"id": c["id"], "text": c["text"], "equipment": c["equipment"], "sources": c["sources"], "status": c["status"]} for c in store["causes"]
              if c["parameter"] == parameter and c["guide_word"] in gws and (keep is None or c["equipment"] in keep)]
    safe = [{"id": s["id"], "text": s["text"], "sources": s["sources"], "status": s["status"]} for s in store.get("safeguard_types", []) if s["applies_to"] in ("any", parameter)]
    ex = [{"id": e["id"], "context": e["context"], "causes": e["causes"], "consequence": e["consequence"], "responses_in_source": e["responses_in_source"], "sources": e["sources"]}
          for e in store.get("worked_examples", []) if e["parameter"] == parameter and e["guide_word"] == guide_word]
    return {"parameter": parameter, "guide_word": guide_word, "causes": causes, "safeguard_types": safe, "worked_examples": ex}
