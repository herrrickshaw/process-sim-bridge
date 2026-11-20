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

## 3. Case schema (sketch; the built version is JSON, see section 9)
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
  cases/*.json         reviewed case records (committed; facts only; JSON so there is no dependency)
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

## 9. Phase 0 status (built 2026-11-20)
Built in `hysys_bridge/casebook/`: `schema.py` (validator, capability check against the verified unit list, case hash, scenario overrides, conversion to the Flowsheet IR), `runner.py` (every scenario times every property package on DWSIM, comparison, package spread, reproduce check), `ledger.py` (append-only `studies/ledger.jsonl`), `tools.py` (`casebook_list`, `casebook_validate`, `casebook_run`; the ledger is written only with `confirm=true`; case ids are restricted to `[a-z0-9-]` so no path traversal) and a CLI (`python3 -m hysys_bridge.casebook validate|run|ledger`). First case: `studies/cases/cumene-alkylator-feed-heater.json`. Changes from the plan: JSON instead of YAML (no dependency in this repo), and `scenarios` were added to the case record (named overrides, each with a stated reason, validated like the base case).

Measured on the real DWSIM server (podman, `ghcr.io/danwbr/dwsim-mcp`), published duty 2.106e8 kJ/h (HYSYS, NRTL), 9 runs = 3 scenarios x 3 packages, all solved, no spec mismatches on read-back:

| Package | Base duty, kJ/h | vs report | Propylene 0.00571 instead of 0.00574 | Mass flow from mole flow (+0.4%) |
|---|---|---|---|---|
| NRTL | 2.1768e8 | +3.4% | -0.004% | +0.400% |
| Peng-Robinson | 2.0535e8 | -2.5% | -0.001% | +0.400% |
| SRK | 2.1032e8 | -0.1% | -0.001% | +0.400% |

Reading: the package spread (5.8 to 5.9% of the report value in every scenario) is about ten times the effect of either reconstruction uncertainty, so the unexplained 0.4% of stream makeup and the second propylene reading do not matter here; the package choice does. The mass-flow scenario moves the duty by exactly the flow change, as it should for a heater with the outlet temperature fixed. The base numbers equal the earlier hand run in `docs/MODEL_SCENARIOS.md`, which proves repeatability, not accuracy: accuracy is the comparison with the report, and a single case cannot settle it. The case stays at status `built`, not `verified`, because no person has reviewed the reconstructed composition (`review.human` is false).

Limits: the 9 ledger rows carry git commit 39e3ec0, the commit before this code was committed; the case hash (36e597defef1) is the reliable link to what ran. One case only; no recycle, no multi-unit flowsheet yet.

## 10. Testing plan
Principles: a rule is only real if a planted fault breaks it; a check needs a positive control; verify before claiming; small steps, each ending green.

| Layer | What | Where | Status |
|---|---|---|---|
| Unit, validator | One failing fixture per validation rule (about 40 planted faults, each reported exactly once; first version had 15 and only covered 14 of 36 rules, see the test audit below). Examples: missing anchor, missing pressure basis, composition not summing to 1, reconstructed without check, verified without human review, bad targets, empty reported, missing licence, missing molar masses, scenario without a reason, bad override path, bad scenario composition, tolerance 0, bad reproduce block, unknown compound) | `hysys_bridge/tests/test_casebook.py` | Done |
| Unit, conversion and compare | gauge to absolute, mass fractions sum to 1, scenario changes only its override and leaves the base untouched, tolerance edges, zero reference | same | Done |
| Integration, fake transport | Runner over all scenarios and packages with a deterministic stand-in that returns an invented enthalpy; asserts the arithmetic and that a wrong answer is reported as outside tolerance (negative control) | same | Done; catches plumbing errors only, not thermodynamics |
| Tool layer | Registration, path-traversal refusal, `DWSIM_MCP_CMD` required, ledger written only with `confirm=true` | same | Done |
| Live, opt-in gate | Reproduce the hand-run package results within 1%, 9 of 9 solved | `python3 -m hysys_bridge.casebook run <case> --reproduce` | Done for the cumene case |
| Regression, drift | Compare each new run with the last ledger row of the same case hash; flag changes over 1% | planned in `casebook/compare.py` | Not built |
| Closure and sanity checks on extracted cases | Mass balance, duty equals enthalpy difference, composition sums | Phase 2 | Not built |
| Independent oracle | A second source for the same case (another paper, vendor data, or the commercial tool) | Phase 3 | Not built |

Scenario policy: a scenario varies a value inside its stated uncertainty and gives the reason in the case file; the property package is the other axis. Nothing is adjusted to hit a published number. Scenarios worth adding as soon as their cases are extracted: feed composition ranges for the oil and gas separation plant, part-load points for the CCGT cases, and stack temperature and heat-recovery settings for the boiler tools (analytic, no simulator needed).

## 11. What the two skill packs add (read 2026-11-20, README and ETHOS only; nothing installed)
Read: `addyosmani/agent-skills` (README: lifecycle spec, plan, build, test, review, ship; small atomic tasks; "tests are proof"; verification gates and anti-rationalisation tables per skill) and `garrytan/gstack` (README and ETHOS.md: sprint of think, plan, build, review, test, ship, reflect; `/test-audit` for tests that cost more than they protect, `/review` with gate integrity, `/qa` for CLIs and APIs, `/eval-plan` to preregister a paid eval, "search before building", "complete coverage, minimal code"). Their skill bodies were not read, their install scripts were not run, and the productivity figures in gstack's ETHOS are the author's claims.

What this plan already does the same way: spec-first case records, one slice at a time with a green suite at the end of each, planted-fault tests, a negative control, a ledger instead of a "done" claim. What to take from them next:

| Idea | Source | Action in this plan |
|---|---|---|
| Audit the tests themselves | gstack `/test-audit` | After each phase, check that no test only greps source or asserts nothing, and that every validator rule still has a failing fixture; run it before Phase 1 |
| Gate integrity: a gate must be able to fail | gstack `/review`, unlazy | The live reproduce gate compares with my own earlier run, so it shows repeatability only. Add an independent oracle per case (a second source) before a case can reach `verified`; already in the testing plan, now a hard rule |
| Preregister the evaluation | gstack `/eval-plan` | Before the Phase 5 copilot evaluation, write the pass bars, the arms (copilot with and without the tools) and stop rules in a file, then run |
| Spec before code, small atomic tasks | agent-skills `/spec`, `/plan` | Each new case gets its record written and validated before any run; each extraction is one paper, one commit |
| Independent review before merge | both | Have the casebook reviewed by a second reader, human or separate agent given the code, not my conclusions, before PR #1 is merged |
| Search before building | gstack ETHOS | Before the Phase 2 extractor, look at what the surveyed studies (ChemE-as-Code, Aspen Assist) already do for provenance and acceptance criteria |

## 12. Test audit of the casebook tests (2026-11-20, before Phase 1)
Method: mutation check, not line coverage. Each validation rule (36 `append` lines in `schema.py`) was switched off in turn and the casebook tests re-run; then 11 hand-written mutants of the runner, converter, ledger and tools (flipped enthalpy difference, dropped gauge-to-absolute conversion, dropped mole-to-mass conversion, ledger opened for write instead of append, ignored `confirm`, loosened case-id rule, ignored scenario override, and others). A mutant that leaves the tests green points at a test that does not protect that behaviour. Line coverage was misleading here: it showed every rule line as run because each rule is one `if ...: append` line.

Findings and fixes:
- **22 of 36 validation rules had no failing test** (the earlier claim of one fixture per rule was wrong). Added 22 planted-fault fixtures; mutation survivors are now 0 of 36.
- **A single base fault was reported three times** (once for the base case and once per scenario). Scenario validation now reports only the problems a scenario adds. Planted-fault tests now assert the exact count, so a rule that fires for the wrong reason or twice fails.
- **Path-traversal test was vacuous**: it passed because the file did not exist, not because the id rule worked (mutant with the rule removed survived). It now plants a real case file one directory up and requires the id-rule message.
- **Reproduce check** only had exact-match cases, so a broken tolerance survived. Added a case 0.5% off (matches) and 2% off (does not).
- **Package spread** was never asserted, and it was computed across scenarios until a mutant showed the tests could not tell. Added a stand-in transport whose enthalpy depends on the package and checked the spread per scenario against the closed form.
- **Environment leak**: two tests removed `DWSIM_MCP_CMD` from the process environment for the rest of the run. They now restore it. The same pattern exists in `test_refinery_link.py` and `test_safety_link.py` (not changed here).

Result: 17 casebook tests, 47 of 47 mutants caught. Not covered by this audit: the real-server path (`StdioTransport`) and `stream_T_C`/`stream_P_kPa` extractors, which only the live gate exercises.

## 13. Phase 1, case 1: oil and gas separation plant (assessed 2026-11-20, not yet built)
Source: A. Andreasen, "Evaluation of an Open-source Chemical Process Simulator Using a Plant-wide Oil and Gas Separation Plant Flowsheet Model as Basis", Period. Polytech. Chem. Eng. 66(3), 503-511 (2022), doi 10.3311/PPch.19678. Open access, Creative Commons Attribution (the extracted text does not give the version). Fetched in full by `fetch_source.py` (route: DOI location, pp.bme.hu, 42,312 characters); read in full. Supplementary files are public on GitHub (`andr1976/dwsim-paper`, MIT).

What the paper gives (facts, with attribution): a plant with 3 separation stages (70 C/31.5 barg, 8 barg, 65 C/1.5 barg), three compressor stages with suction coolers and scrubbers, a condensate recycle pump, a dew-point control unit with a cross exchanger and a refrigerated cooler, an export compressor (188.6 barg) and cooler (40 C), an oil export pump (60 barg) and cooler (48.5 C); Peng-Robinson with the equation of state for liquid density and departures; all pumps and compressors at 75%; well fluid of CO2 and alkanes with 8 pseudo-components (Table 2: MW 108 to 413, with critical properties from Twu's method). Reported results, HYSYS v11 against DWSIM 6.7.0 for one operating point: gas export 5102.0 against 5102.4 kmol/h, liquid export 2764.3 against 2763.0 kmol/h, export MW 20.99 against 21.02 and 201.9 against 201.9, RVP 10.1 against 10.1 psia, well-fluid GOR 2.171 against 2.174; driver duties within about 1% (largest, the MP compressor, just above 1%); two small heat-exchanger duties off by 5.8% and 3.9%. A 100-sample Monte Carlo study over 10 variables (91 converged in DWSIM) with R2 of 0.991 to 0.999.

Why it does not fit the Phase 0 pipeline as it stands:
1. **Pseudo-components cannot be created through the DWSIM MCP server's tools** (`dwsim_thermo_add_compounds` takes database names only; no hypothetical-component tool among its 58). The plant cannot be rebuilt from our case record without them, and substituting database alkanes would change the fluid, so the HYSYS numbers would no longer be a valid reference.
2. About 25 units and recycles (tear streams); the server does list a `Recycle` unit type, but nothing recycle-related is verified.
3. The paper's RVP uses a Python script unit operation.

A route that avoids (1): the server can load a flowsheet file (`dwsim_flowsheet_load`), and the author published the DWSIM file (`simulations/Base_case_bechmark.dwxmz`, 617,611 bytes) and the 100-sample plan with HYSYS and DWSIM responses (`data/*.csv`, about 10 to 25 KB each). Loading and solving it would reproduce the paper's DWSIM column and test the server's handling of recycles, pseudo-components, compressors, valves and splitters in one step, and the CSVs give 91 reference points for a later study. This needs three things not done yet: downloading those files, loading a third-party file into the simulator (DWSIM flowsheets can carry script unit operations, and this one does), and a container command that mounts the file read-only (the current command has no mounts). The container's `--network none` and a read-only single-file mount bound the exposure, but the file is third-party code, so it needs your go-ahead first. A schema extension for "native file" cases (file hash and licence instead of streams and units) is needed either way.

### 13.1 Outcome of the approved download and load (2026-11-20)
Downloaded to `studies/raw/dwsim-paper/` (gitignored) from `andr1976/dwsim-paper` (MIT): `Base_case_bechmark.dwxmz` (617,611 bytes, sha256 1c86ad37...), `HYSYS_result.csv`, `DWSIM_result.csv`, `DWSIM_results_cleaned.csv`, `raw_testplan.csv`, `LICENSE`. Before loading, the file's XML was searched without running anything: it holds one script (the RVP loop: it sets a stream's temperature and pressure, flashes, and adjusts pressure until gas volume is 4 times liquid volume; no file, network or process calls), and its objects are 55 material and 17 energy streams, 8 coolers, 8 vessels, 5 mixers, 4 compressors, 4 recycles, 3 specs, 2 pumps, 2 valves, 2 heaters and the script unit. Saved by DWSIM 6.5.4 on Windows, 2021.

**The server cannot load it.** `dwsim_flowsheet_load` (container mount read-only, `--network none`, only the one directory mounted) fails with `InvalidOperationException: Collection was modified; enumeration operation may not execute.`, the same on the `.dwxmz` and on its extracted XML. Checks to find the cause, using throwaway copies deleted afterwards: removing the script unit, the recycles, the specs, or all three together, or the convergence history, did not change the error; removing the graphic objects changes it to a `NullReferenceException`, as do removing the settings or the property-package blocks. So the failure is in the loader's handling of this 2021 file as a whole, not in a unit we could drop. The loader itself works: a flowsheet the server saved was loaded back in the same session. Nothing was solved and no result was produced from this file.

Options, in order of cost: (1) open the file in a current DWSIM on a desktop and save it again, then retry (needs a person with DWSIM; the published file is then the author's flowsheet in a new format); (2) report the loader error to the `dwsim-mcp` maintainers with the message and the file's DWSIM version (a public post, so it needs your go-ahead; a draft is easy to write); (3) wait for pseudo-component and recycle support in the tool set, then rebuild the plant through our case schema.

**The reference data is usable now, without the simulator.** The 100-sample results are plain numbers (no headers): `HYSYS_result.csv` has 3 columns (liquid export flow, total power, RVP, in the paper's order, by my reading) and the DWSIM files have a fourth column (about 4.00, meaning not determined). Checks that my reading is right: the nine DWSIM rows with no valid result are rows 24, 47, 52, 54, 55, 60, 65, 93 and 96 (0-based), exactly the nine sample indexes the paper lists as unconverged; and on the 91 converged rows of the cleaned file the DWSIM-versus-HYSYS R2 is 0.9885 (liquid flow), 0.9983 (power) and 0.9988 (RVP), against 0.9912, 0.9988 and 0.9991 in the paper's Table 6: close but not identical, possibly because the repository holds a slightly different set of manual re-runs than the paper's final one. The raw `DWSIM_result.csv` gives R2 of only 0.952, 0.974 and 0.959, so it is the pre-cleaning data and must not be used. The median absolute difference on the cleaned data is 0.07% (flow), 0.16% (power) and 0.21% (RVP), the largest 0.7%, 2.0% and 1.8%. `raw_testplan.csv` holds 10 factors scaled to the unit interval (the paper's Table 3 gives the bounds); the scaling is my reading, not stated in the file.

What this gives the casebook now: a reference dataset for a future study (HYSYS as the reference tool, 91 points) and, once a route to run the plant exists, a ready regression target. It does not yet verify any unit type on our backend.

## 14. Phase 1, case 2: the DWSIM tutorial recycle loop (built and run 2026-11-20)
Case `studies/cases/water-recycle-loop-tutorial.json`: fresh water at 300 K and 1 atm, 1.0 kg/s, into a mixer, a heater to 350 K, a splitter (70% to product), and a Recycle block returning the other 30% to the mixer. Source: DWSIM's own tutorial page (read in full); its expected values are rounded (about 1.0, 1.43 and 0.43 kg/s), so the case uses the exact values from the mass balance it states: product = fresh feed, mixed = fresh / split ratio, recycle = mixed x (1 - ratio). The reference is therefore analytic, which is what a loop test wants: no other simulator's numbers in the way.

What was learned about the server's Recycle, by asking it (an unknown property name returns the list of valid ones):
- `Recycle` units accept `AccelerationMethod`, `MaximumIterations`, `SmoothingFactor`; results report `Mass Flow Error` (kg/h), `Temperature Error` and `Pressure Error`. There is no separate "estimate" property: the estimate is whatever is specified on the Recycle block's outlet stream.
- A `Splitter` takes `OperationMode = SplitRatios` and `SR1` (first outlet's share; the other is the balance). `SR2` is a result.
- The loop solved with no estimate and with an estimate of 0.43 kg/s alike (this server's Recycle did not need one for this loop, so the starting-point ladder from the DWSIM docs is not exercised yet). The flowsheet check reports no findings and the degrees of freedom are zero.

Run through the casebook (3 scenarios of the split ratio plus the base, times Steam Tables and Peng-Robinson, 8 runs, all solved, no findings, spec read-back clean): largest deviation from the closed form 0.003% at 70/30, 0.000% at 50/50, 0.001% at 90/10 and **0.038% at 20/80** (80% of the flow returned, where the tutorial warns of tens of passes). Mass flows are identical across the two packages, as they should be. A server residual of 0.09 kg/h on the Recycle block's mass-flow error was reported in the probe. Ledger: 8 rows for case hash d9ccab55fc6a.

Consequences:
- `recycle` is now an accepted unit type in the case schema and is on the verified list (`UNIT_PARAMS_VERIFIED`), with this case as the evidence; the splitter's `split_ratio` parameter reaches the server (a unit test that drops the parameter fails, and a mutation check confirmed it).
- Case records can now carry unit parameters (`units[].params`), computed streams without a published T and P, mass-flow reference values (`stream_mass_kg_h`), and scenario overrides on units and on reported values (each scenario states its own expected result).
- Still open for recycles: acceleration and tolerance settings are not exposed in the case schema; the estimate ladder is unexercised; no loop with a phase change, a purge or a reactor yet. The DWSIM tutorial's own exercise "100% recycle" (split 0/1) should fail to converge and is a good negative control to add.

## 15. Phase 1, cases 3 and 4: the DWSIM mixer and flash drum tutorials (built and run 2026-11-20)
Both tutorial pages were read in full first. Cases: `water-mixer-tutorial` and `water-ethanol-flash-drum-tutorial`.

**Mixer** (100 kg/s water at 300 K and 50 kg/s at 348 K, 1 atm). The tutorial's "~316 K" is rounded, so the reference temperature comes from an independent enthalpy balance with CoolProp (IAPWS-95): 316.0141 K. Scenarios: flows swapped (332.0199 K) and equal flows (324.0193 K), each with its own independently computed expectation. 9 runs (3 scenarios x Steam Tables, Peng-Robinson, SRK), all solved, no findings, all within tolerance. Temperature error against the independent value: Steam Tables -0.004 K, SRK -0.003 to -0.008 K, Peng-Robinson +0.016 to +0.020 K. Outlet mass flow exact (540,000 kg/h), pressure 101.325 kPa, vapour fraction 0.

**Flash drum** (1 kg/s of 50/50 water and ethanol by mass, 300 K, heated to 360 K, 1 atm, then a separator vessel; NRTL). The tutorial gives ranges and rounded "~" values, not exact ones, and no independent oracle exists in this repo for NRTL water/ethanol, so the case checks the published ranges, the exact mass balance, the approximate values with a 5% tolerance (two digits, "depends on NRTL"), and two scenarios derived from its stated bubble (about 355 K) and dew (about 365 K) points: 350 K must give no vapour, 370 K no liquid. 9 runs, all solved, no findings.

| Package | Vapour fraction (mole) | Vapour, liquid kg/h | Ethanol mass fraction, vapour / liquid | Against the tutorial |
|---|---|---|---|---|
| NRTL (the tutorial's) | 0.548 | 2298 / 1302 | 0.661 / 0.216 | all checks pass; approximate values within 0.3%, 0.5%, 0.1% and 1.8% |
| Peng-Robinson | 0.662 | 2750 / 850 | 0.653 / **0.006** | ranges pass; approximate values fail (+19%, -34%, ... -97%) |
| SRK | 0.620 | 2645 / 955 | 0.678 / **0.007** | same |

Reading: with NRTL the server reproduces the tutorial's numbers. Peng-Robinson and SRK without binary interaction parameters put almost all the ethanol in the vapour (liquid ethanol 0.6%), which is wrong for this polar mixture, exactly the warning in the DWSIM documentation ("PR or Raoult's law for a polar mixture misses the azeotrope"). The range checks alone would have passed these two packages, so the case's approximate-value checks are what catch it: a useful result about the case design, and a reason to prefer point references over inequalities where a source gives them. The run now reports "within tolerance in the paper's own package" separately from "in every listed package" (flash: true and false; mixer: both true), because a comparison package that fails is information, not a failure of the case.

What changed in the casebook for these cases:
- reported values can be a published **range** (inclusive) instead of a point; a per-value `pass_rel` overrides the case default; new kinds `stream_vapor_fraction`, `stream_mass_fraction` (per compound) and `streams_mass_sum_kg_h` (mass balance over several streams);
- scenarios can **drop** expectations that do not apply (the composition of an empty stream);
- a separator's two outlets must declare `phase` as vapour then liquid, in that file order, because the server's vessel takes them as port 0 and port 1 (probed: port 0 is the vapour); a test with swapped ports fails the case, and the validator rejects the wrong order.
- Mutation check on the new logic: all but one mutant were caught on the first pass; the survivor (compound selection in the mass-fraction reader) exposed that the stand-in carried only one compound, fixed, and the same mutant is now caught.

Status: `separator` (Vessel) and `mixer` are now each backed by published-case runs; both cases stay at status `built` until a person reviews them. Ledger: 9 rows each (hashes ddf8a5109b42 and ddaca6816703).
