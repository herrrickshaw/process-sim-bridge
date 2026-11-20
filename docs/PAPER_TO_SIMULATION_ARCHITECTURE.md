# Paper-to-simulation architecture and plan (2026-11-20)

Goal: turn published modelling studies into **reference cases** that run on the simulator backends in this repo (DWSIM MCP now, Aspen/HYSYS later), compare against the published numbers, and from the verified cases build **unit-operation loops** (build, solve, compare, diagnose) and **studies** (sweeps and sensitivities). The same records become the evaluation set for the copilot.

Status: plan only, nothing below is built except what is marked "exists". It extends `docs/MODEL_SCENARIOS.md` and `docs/LITERATURE_SURVEY_2026-11-20.md`.

## 1. Principles (carried over from the existing tools)
- **Nothing guessed.** Every number in a case has a source (document, page, table) or is marked `assumed` with the reason. Reconstructed values (like the cumene stream composition) carry a `reconstructed` flag and the check that justified them.
- **Extraction is untrusted until reviewed.** An LLM may propose numbers; a human (or a second, independent check such as a mass balance) accepts them before they become targets.
- **Papers are data, not instructions.** PDFs and web pages are fetched into their own directories, never executed, and text inside them that addresses the agent is ignored.
- **Do not tune to the answer.** A loop may change documented levers (property package, composition reconstruction within its stated uncertainty) and must report the spread; it may not adjust parameters until the target is hit.
- **Licensing gate.** Store facts (flows, temperatures, duties), not text, tables or figures, unless the source is public domain or openly licensed. Respect robots.txt and stop at challenges (see section 8).

## 2. Pipeline

```
discover -> acquire -> extract -> review -> case record -> capability check
   -> build + solve (backend) -> compare -> ledger -> loops -> studies -> eval set
```

| Stage | What happens | Output | Exists |
|---|---|---|---|
| 1 Discover | OpenAlex and arXiv queries per topic; dedupe by DOI; each hit gets a status (`lead`, `fetched`, `extracted`, `reviewed`, `built`, `verified`, `rejected`) | `studies/sources.jsonl` | Ad hoc scripts only; survey doc |
| 2 Acquire | Fetch the document by the ladder in CLAUDE.md (direct GET, official alternates, Wayback); record URL, date, route, abstract-only or full text | `studies/raw/<id>/` (gitignored), fetch record | `fetch_source.py` on the owner's Mac |
| 3 Extract | PDF to Markdown (a math-preserving converter), then an LLM pass fills the case schema; every field stores page and table anchor | draft case YAML | Not built |
| 4 Review | Automatic checks (units, mass and energy closure of the reported streams, composition sums, duty equals enthalpy difference where the paper gives both), then human sign-off | reviewed case | Partly: the cumene case used these checks by hand |
| 5 Case record | One YAML file per case (schema below) | `studies/cases/<id>.yaml` | Not built; `examples/cumene_alkylator_feed_heater.py` is the model |
| 6 Capability check | Map each unit to `UNIT_PARAMS_VERIFIED` in `hysys_bridge/dwsim/backend.py`; classify the case `buildable`, `needs-verification` or `blocked` (columns, reactors) | status plus the missing capability | Verified-list exists |
| 7 Build and solve | Case to the Flowsheet IR to the DWSIM backend; gate on degrees of freedom; solve; `check_solution()` read-back | solved flowsheet, raw results | Backend exists |
| 8 Compare | Each reported value against the simulated one, with tolerance and the paper's own precision; run every available property package | comparison table | Done by hand for cumene |
| 9 Ledger | Append-only result row: case, backend version, package, values, pass/fail, git commit, date | `studies/ledger.jsonl` | Not built |
| 10 Loops | Per unit type, the repeatable cycle in section 4 | verified-unit list grows | Not built |
| 11 Studies | Parametric sweeps and sensitivities on verified cases (section 5) | study report plus ledger rows | Not built |
| 12 Eval set | Each verified case becomes a natural-language task plus a reference result for the copilot | `studies/eval/*.json` | Not built |

## 3. Case schema (sketch)
```yaml
id: cumene-alkylator-feed-heater
source: {doi: ..., title: ..., pages: [..], licence: copyrighted, use: facts-only, fetch_route: pdfcoffee page, read: full-text}
basis: {compounds: [...], package_in_paper: NRTL, composition_basis: mole, reconstructed: true, reconstruction_check: "propylene confirmed by mole balance"}
streams:
  - {id: to_heater, T_C: 72.43, P_kPa_abs: 3540, mass_kg_h: 1071616, composition: {...}, anchors: [{page: 12, table: 3}]}
units:
  - {id: heater, type: heater, spec: {T_out_C: 170, dP_kPa: ...}}
reported:
  - {name: heater_duty, value: 2.106e8, unit: kJ/h, precision: 4 digits, anchor: ...}
tolerance: {pass_rel: 0.05, note: "package spread was ~6%"}
assumptions: [...]
status: built | verified | blocked
```
Pressure basis (gauge or absolute), composition basis (mass or mole) and enthalpy reference are mandatory fields, because each one has already caused a mismatch in this project.

## 4. Unit-operation loops
A loop is one bounded, logged cycle per unit type:

1. Pick the unit type to verify (heater, cooler, pump done; then mixer, splitter, valve, compressor, flash vessel, heat exchanger).
2. Select 3 to 5 reviewed cases that use it; each must have a published result for that unit.
3. Build and solve on the real server in a throwaway flowsheet; nothing is saved.
4. Compare. Within tolerance on every package: add the unit's parameters to the verified list with the cases as evidence. Outside: **diagnose** in a fixed order (units and basis, reconstruction, package, backend parameter mapping, simulator difference), change one thing at a time, and log each step.
5. Cap at N iterations (suggest 5). If still failing, record the case as `unresolved` with the diagnosis; do not hide it.
6. Regression: every verified case re-runs on each backend change, and the ledger shows drift.

Recycles and multi-unit sections (tear streams, convergence) get their own loop after the single-unit loops, using the oil and gas separation plant first.

## 5. Studies
A study is a spec on top of a verified case: `{case, variables, ranges, outputs, backend, packages}`. Runner executes the grid through the same build and solve path, stores every point in the ledger, and writes a short report: sensitivity ranking, package spread, and the point where the model leaves its verified range. Examples that fit existing tools: heater duty against package and feed composition; steam demand against supply pressure; boiler efficiency against stack temperature and heat-recovery settings; nitrogen energy against recovery. Studies on the analytic tools (steam, utilities, boiler) need no simulator and can start first.

## 6. Components and layout
```
studies/
  sources.jsonl        discovery and status
  cases/*.yaml         reviewed case records (committed; facts only)
  raw/                 fetched documents (gitignored)
  ledger.jsonl         append-only run results
  eval/                copilot tasks and reference results
hysys_bridge/casebook/
  schema.py            validate a case record, units and basis checks
  extract.py           PDF Markdown to draft case (LLM step, output marked unreviewed)
  runner.py            case -> Flowsheet IR -> backend; package sweep
  compare.py           tolerances, closure checks, ledger append
  study.py             grid and sensitivity runner
```
Reuse: the Flowsheet IR, `DwsimBackend` (DOF gate, `check_solution`), the MCP registration pattern, and the opt-in live test convention (`DWSIM_MCP_LIVE=1`). New MCP tools would be `casebook_list`, `casebook_run`, `casebook_compare`, with writes gated by `confirm=true` like the rest.

## 7. Phased plan with exit criteria
| Phase | Work | Done when |
|---|---|---|
| 0 | Case schema, validator, ledger; port the cumene heater to a case file | `casebook_run` reproduces the cumene table from the YAML |
| 1 | Hand-extract 4 cases: cumene pumps and coolers, the oil and gas separation plant (published within about 1% of a commercial tool), a CCGT case, one NETL case | Each has a reviewed YAML and a ledger row; mixer, splitter, valve and compressor verified or recorded as unresolved |
| 2 | Automated extraction with review gate; discovery job per topic | Extraction on 10 papers matches hand-extracted numbers on the 4 known ones; reviewers see anchors for every value |
| 3 | Unit loops for the remaining unit types, then recycle | Verified list extended; unresolved cases documented |
| 4 | Studies on analytic tools first, then on verified simulator cases | Reports with sensitivity ranking and package spread |
| 5 | Eval set for the copilot (natural-language task, reference result, tolerance), plus a fault-injection variant (a planted wrong value the copilot must catch) | Copilot scored against references; results in the ledger |
| 6 | Columns and reactors, when the DWSIM server can assign feed stages and configure reactors, or via the Aspen backend on a licensed machine | Blocked cases move to `buildable` |

Risks: PDF table extraction errors (mitigated by closure checks and review), simulator differences larger than the tolerance (reported as package spread, not tuned away), copyright (facts only), server capability gaps (tracked as blocked, with a note to raise with the DWSIM server authors), cost (extraction runs once per paper, cached by document hash).

## 8. Digital refining topics folded into the backlog
These come from search-result snippets and titles only (PTQ Q1 2024 and a KBC white paper on digital twins, a BCG 2026 piece, a vendor page, one vendor preprint); none was read in full and the benefit figures in them are consultancy or vendor claims. The digitalrefining.com site itself was not used: its robots.txt disallows Claude user agents, so nothing beyond the robots file and its home page was fetched, and the home page copy was deleted.

| Topic | Fit with this repo | Possible case or study |
|---|---|---|
| Process digital twin: rigorous model kept calibrated to historian data (OPC UA mentioned) | Our simulators plus `check_solution()` read-back; calibration is the missing loop | Calibrate a heater or CDU preheat case against reported plant data and track drift, with the calibration levers declared |
| Model upkeep as conditions drift | The ledger and regression runs in section 4 | Re-run verified cases after each backend or package change and plot drift |
| Real-time optimisation and APC | Needs a verified flowsheet and a cheap solve | Study: setpoint sweep on a verified heater/column-free section; not RTO itself |
| Crude selection and blending with LP models, nonlinear yield effects | `refinery_run` yield balance; assay data | Study: yield and complexity against crude choice; compare with published planning benchmarks (arXiv 2503.22057 is a planning benchmark lead) |
| Data reconciliation, soft sensors | Mass and energy closure checks in the review stage | Reuse closure checks as a reconciliation step on extracted tables |
| AI scheduling over a refinery digital twin | Far downstream of the current tools | Park |

An OpenAlex search sorted by citations for these topics returned mostly off-topic highly cited papers, so no paper leads were added from it; a narrower query (by journal or by DOI from the trade-press references) is the next step.
