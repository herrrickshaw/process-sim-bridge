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

## 16. Phase 1, cases 5 and 6: heater and cooler (built and run 2026-11-20)
Page read in full first: DWSIM "Heater and Cooler" tutorial (water, 1 kg/s, 25 C to 80 C and back, Steam Tables, expected "~230 kW"; its hand calculation gives 229.9 kW with Cp 4.18). Because "~230" is rounded, the reference duties are an independent calculation: CoolProp (IAPWS-95) enthalpy difference at the stated pressures, 230.135 kW. Cases: `water-heater-cooler-tutorial` (heater then cooler, scenarios: heat to 95 C, double flow, heat through the boiling point to 110 C, and a 100 kPa pressure drop across the heater) and `steam-condenser-cooler-independent` (a cooler with a phase change, no published case, so its source is marked `computed`: steam at 120 C cooled to 60 C, to 99 C, and only to 105 C). Both cases are checked on outlet temperature, pressure, vapour fraction, each duty, and for the heater-then-cooler loop that the two duties cancel. 24 runs in all, all solved, no findings, every specification read back.

Duty error against the independent value (Steam Tables is the tutorial's package):

| Case and scenario | Steam Tables | Peng-Robinson | SRK |
|---|---|---|---|
| Heat 25 to 80 C (and the 95 C, 2 kg/s variants) | -0.032%, -0.027%, -0.032% | +7.9%, +8.0%, +7.9% | +15.1% for all three |
| Heat through boiling to steam at 110 C | -0.001% | +3.9% | +6.7% |
| Condense 120 to 60 C | 0.000% | -3.6% | -6.1% |
| Condense 120 to 99 C | -0.002% | -3.3% | -5.5% |
| Cool vapour only, 120 to 105 C (a small duty) | +0.063% | +6.3% | +6.2% |

Reading: Steam Tables reproduce the independent duty to a few hundredths of a percent, including through a phase change, so the heater, the cooler and our duty extraction (stream enthalpy difference times mass flow) are correct for them. The two cubic equations of state are 8% and 15% off for liquid water, and 4% to 7% off through a phase change: not a bug in our mapping (the same flowsheet and the same parameters give the exact answer with Steam Tables) but the known weakness the DWSIM documentation names ("for pure water and steam: always Steam Tables"). The default case tolerance (0.5%) therefore fails for those two packages, and the run reports that separately from the paper's own package, which passes.

Two things found along the way:
- **My own scenario was wrong.** In the pressure-drop scenario the heater (301 to 201 kPa) and the cooler (201 kPa) no longer follow the same path, so the net duty is not zero but the difference of the two independent values, -333.3 kJ/h; my first run flagged it (Steam Tables gave -333.37). The expectation was corrected from the independent calculation, which was available before the run, not from the simulator output; the scenario now carries a 2% band around -333.3 and says why.
- **The sign of the heater's pressure-drop parameter** (a drop is sent as a positive `DeltaP`) is now covered by a test and a mutant that flips it is caught. The live pressure-drop runs match the independent duties with Steam Tables to -0.032%, the same as without a drop.

Casebook changes: reference kind `units_duty_sum_kJ_h` (net duty over several units); source `read: computed` for a reference that is a calculation, not a document. Mutation check: 5 of 5 new mutants and all 46 validator rules caught. Ledger: 15 and 9 rows (hashes 10ff22c8381c and 429e5cc26ffe). Both cases stay at `built` until a person reviews them.

## 17. Phase 1, cases 7 to 9: the FOSSEE DWSIM manual (read and built 2026-11-21)

Source: SASTRA FOSSEE Centre, "Process Simulation Using DWSIM" (Naren, v02, December 2017, DWSIM 5.1 Classic UI), eleven basic exercises, fetched once with `fetch_source.py` (robots.txt allowed) and read in full as text. **The results tables in the manual are images, so the document gives specifications but no readable expected numbers.** Every reference below is therefore an independent calculation (CoolProp 7), not a transcribed value, and each case says so in `source.note`. Licence: none seen on the document; only facts (specifications) are used, no text or figures.

| Exp | Manual title | Status | Reference |
|---|---|---|---|
| 1 | Mixing of ideal liquid streams | built, run | exact mole and mass balance, ideal mixing keeps 30 C |
| 7 | Simulation of a flash column | built, run | Rachford-Rice with CoolProp vapour pressures |
| 9 | Determination of heat duty of heater | built, run | CoolProp IAPWS-95 enthalpy difference |
| 2, 3 | Pure-component properties, binary VLE | not built | property-viewer and Binary Envelope utilities, not flowsheet units |
| 5 | Material balance on a reactor from conversion data (ammonia) | built, run (section 18) | exact mole balance and the standard heat of formation |
| 4 | Equilibrium conversion (water-gas shift) | built, run (section 19) | K and heats of formation from the NIST-JANAF tables |
| 6 | CSTR with first-order kinetics | not built | the server has tools for conversion and equilibrium reactions only, no kinetic reaction, and a CSTR needs one |
| 8 | Shortcut column | not built | server unit exists; reference would be Fenske-Underwood-Gilliland, needs a relative volatility choice |
| 10 | Heater and cooler as heat exchanger (styrene and toluene) | not built | no independent oracle: styrene is not in CoolProp; the manual links the heater to the cooler's energy stream, which our IR cannot express |
| 11 | Rigorous shell-and-tube exchanger | not built | needs exchanger geometry parameters; unit not driven |

### Results on the real DWSIM server (podman, `ghcr.io/danwbr/dwsim-mcp`)
All 26 runs solved, no findings, no spec mismatches on read-back. Ledger rows 6, 8 and 12 (hashes c97415f5341b, 63439bbbbf22, 6a840512eaea).

**Exp 1, methanol/water mixer (2 scenarios x 3 packages).** Mass flow and mass fraction exact in every package. Outlet temperature: Raoult's Law 30.0 C and NRTL 30.0 C (NRTL gave no mixing heat effect in this server, so it does not answer the manual's "what if enthalpy of mixing is not negligible"); Peng-Robinson 28.2 C (-6.1%) and 27.5 C with pure methanol as stream 2 (-8.3%). Paper package within tolerance; not every package.

**Exp 9, water heater (2 scenarios x 4 packages).** 50 kg/h, 25 to 90 C, independent duty 13,607 kJ/h (3.78 kW). Steam Tables -0.0%, Peng-Robinson +8.0%, SRK +15.1%, **Raoult's Law +1.4%, outside the 1% tolerance I fixed before the run, so the paper's own package does not pass.** I did not loosen it. The smaller rise to 60 C passes for Raoult's Law (+0.05%), so the miss grows with temperature, consistent with a liquid heat-capacity correlation that drifts from IAPWS-95 (a reading, not tested here).

**Exp 7, pentane/hexane/heptane flash (4 scenarios x 3 packages).** Independent ideal vapour fraction 0.4330 (mole basis) at 69 C and 101.3 kPa; Raoult's Law gives 0.4353 (+0.5%), vapour and liquid flows within 0.5%, pentane fractions within 0.9%, all inside 3%. The manual's self-learning question 1 (SRK or PR instead): PR -4.9% and SRK -3.1% on the vapour fraction, liquid pentane fraction +3.3% and +4.4%, so both fail the 3% bound and are recorded as expected package differences. Question 2 became three scenarios: below the ideal dew pressure (77.03 kPa, run at 70 kPa), above the ideal dew temperature (77.38 C, run at 80 C), and above the ideal bubble pressure (126.73 kPa, run at 140 kPa); all three phase calls and the single-phase compositions match in every package.

### What the cases needed
Nothing in the casebook code changed except the test fake (it now knows Raoult's Law and N-pentane). New knowledge about the server: the property package list includes "Raoult's Law" (passed through by name); the compound names are `N-pentane`, `N-hexane`, `N-heptane` (a first run with CoolProp's spelling `n-Pentane` failed loudly with a key error, which is the intended behaviour); 1,621 compounds, styrene present.

### Reactor exercises
Exp 5 was built next (section 18). Exp 6 has a closed-form reference (k = 0.005 1/s, V = 2 m3 at 26 m3/h gives tau 276.9 s and conversion k*tau/(1+k*tau) = 0.581) but the server has no kinetic reaction tool, so it stays blocked. Exp 4 was built later from NIST-JANAF values (section 19).

### Tests
`Fossee` class in `test_casebook.py` (5 tests; 47 casebook tests pass): validity and source, mixer reference equals the mole balance, flash reference satisfies the mass and pentane balances, scenarios validate, heater tolerance recorded as fixed before the run. A hand mutant that adds 40 kg/h to the reference vapour flow is caught. Cases stay at `built` (not human-reviewed).

## 18. Phase 1, case 10: conversion reactor, FOSSEE Exp 5 (built and run 2026-11-21)

First reactor in the casebook. Ammonia formation, N2 + 3 H2 -> 2 NH3, 100 kmol/h of 25 mol % N2, 25 C, 1 atm, 20 % conversion of N2, isothermal. Case `ammonia-conversion-reactor-fossee-exp5`; references are an exact mole balance (out: 20 N2, 60 H2, 10 NH3 kmol/h, 90 total) and, for the manual's first self-learning question (heat duty of the reaction), the standard heat of formation of ammonia (-45.9 kJ/mol, three digits), giving -459,000 kJ/h. Scenarios: 50 % and 10 % conversion.

**Result on the real server, 9 runs (3 scenarios x Raoult's Law, Peng-Robinson, SRK): all solved, no findings, no mismatches, every value inside tolerance in every package.** Mass fractions match to 1e-6, the duty to 0.1 % at worst. Ledger 9 rows. Conversion and mole balance do not depend on the package, as expected; the package only enters the duty slightly.

What had to be added:
- **Schema:** unit type `conversion_reactor` whose `params` carry one `reaction` (stoichiometry with reactants negative, base compound, `conversion_pct`, `phase`, an anchor) and a `thermal_mode` (isothermal or adiabatic). The validator checks that the stoichiometry conserves mass with the case's own molar masses, that the base compound is a reactant, the conversion range, phase and mode, that compounds are in the basis, and allows one reactor per case (all reactors would share DWSIM's DefaultSet). Outlets follow the separator rule: a vapour stream then a liquid stream.
- **Backend:** `dwsim_reaction_add_conversion` before the reactor is added, `ReactorOperationMode` = `Isothermic` or `Adiabatic` (the server lists Isothermic, Adiabatic, OutletTemperature, NonIsothermalNonAdiabatic, HeatExchange).
- **Duty:** the stream-enthalpy difference gave 0 (and about -214 kJ/h in the cubic packages) because stream enthalpies do not carry the heat of reaction, so the `unit_duty` kind returned a wrong number rather than failing. For a reactor the duty is now read from the server's `dwsim_explain_result` text ("the duty is X kW"). That is parsing a sentence: if it changes, the read raises instead of defaulting. Found by running, not predicted.
- **Not verified:** port order was only exercised with an all-vapour product (the vapour stream carried all the mass, the liquid stream none); a reactor with a liquid product has not been run. `adiabatic` mode and pressure drop are mapped but not run live.

Tests: `Reactor` class, 6 tests (53 casebook tests): every reaction rule fires, the reaction is added before the reactor with the exact arguments, a run against a fake reactor reproduces the mole balance, a wrong duty in the explanation fails the case, an unreadable duty raises. A 10-mutant check on the new code: 9 caught; the survivor (reaction name) was a real gap and now has an assertion.

## 19. Phase 1, cases 11: water-gas shift equilibrium, FOSSEE Exp 4; and why the CSTR (Exp 6) is still blocked (2026-11-21)

**Equilibrium.** CO + H2O <-> CO2 + H2, 10 kmol/h each of CO and H2O at 800 K and 1 bar, isothermal, vapour phase, partial-pressure basis. The manual gives no equilibrium constant, so the reference is independent: K and the heats of formation from the NIST-JANAF tables for CO, H2O and CO2 (janaf.nist.gov, three pages fetched once each with `fetch_source.py`, 2 s apart): log Kf at 800 K gives K = 4.2267 (Delta G = -9.59 kJ/mol), CO conversion 0.6728, so 3.27 kmol/h CO and H2O, 6.73 kmol/h CO2 and H2. With equal moles on both sides K does not depend on pressure; the table's assumption is an ideal gas. Tolerances fixed before the run: 2 % on compositions (JANAF logKf has three decimals, about 0.4 % in K), 3 % on the duty.

**Result, 9 runs (base, 2 bar, and the manual's self-learning question 1: 1000 K and 2 bar; three packages): all solved, all inside tolerance in every package.** Compositions match the JANAF equilibrium within 0.1 % (the server derives K from its own Gibbs-energy data, so this is an independent confirmation of that data at 800 K and 1000 K). The 2 bar scenario gives the identical composition, as expected for equal moles. The isothermal duty matches JANAF's heat of reaction at the reactor temperature (-36.84 kJ/mol at 800 K, -34.78 at 1000 K) within 0.2 to 0.4 %, so the server does take the heat of reaction at the reactor temperature, not at 298 K (the manual does not discuss duty; this is my expectation, confirmed by the run). Ledger 9 rows (hash 556ec856beb9).

**Code added.** Unit type `equilibrium_reactor` (the server's EquilibriumReactor) with a reaction of kind equilibrium: `basis` from the server's list, `units` (must be `Pa` for partial pressure), optional `lnkeq_expression`; a conversion on an equilibrium reaction is refused. Backend calls `dwsim_reaction_add_equilibrium`; the reactor duty read and one-reactor-per-case rule now cover both reactor types. `NEGATIVE_FLOW` is now classified as a plausibility warning: at 1000 K the empty liquid outlet carried -2.8e-17 kg/s (rounding noise), which showed as an unclassified finding; the number must still be read before dismissing it. Tests: `Equilibrium` class (5 tests; 57 casebook tests), including a check that the reference compositions satisfy K = 4.2267; a 5-mutant check, 5 caught.

**CSTR (Exp 6) stays blocked.** The reaction needs a rate law (first order, k = 0.005 1/s, V = 2 m3 at 26 m3/h, expected conversion k*tau/(1+k*tau) = 0.581). The server creates reactions with `dwsim_reaction_add_conversion` and `dwsim_reaction_add_equilibrium` only (checked against the full list of 58 tools; it has CSTR and PFR unit types but no tool that defines a kinetic reaction). Feeding the 0.581 in as a conversion would only return the number put in, which tests nothing, so I did not do it. Ways forward: a server update with a kinetic reaction tool, or loading a flowsheet file that already carries a kinetic reaction (`dwsim_flowsheet_load` cannot load the 2021 file we tried, see section 13). The reference is ready in this paragraph.

## 20. Phase 1, cases 12 to 14: heat exchangers (built and run 2026-11-21)

New unit type mapping: `exchanger` to DWSIM's HeatExchanger. Streams carry a `side` (hot then cold, inlets and outlets, DWSIM port 0 = hot, port 1 = cold); the unit's `params` give a `mode`, `flow` (CounterCurrent or CoCurrent) and optional pressure drops. Modes: `UA` (U and area given, both outlets computed; DWSIM CalcBothTemp_UA), `hot_outlet_T` (hot outlet temperature given, cold outlet follows; CalcTempColdOut). `cold_outlet_T` (CalcTempHotOut) is mapped and was seen to work in a manual probe (cold outlet 330 K gave hot outlet 340.5 K) but no case exercises it. The server's other modes (CalcArea, CalcBothTemp, shell-and-tube rating, pinch, efficiency) are not mapped. A `unit_duty` reference on an exchanger is the hot side's: negative, the heat removed.

| Case | Specification | Reference |
|---|---|---|
| `water-counter-current-exchanger-tutorial` | DWSIM tutorial "Heat Exchanger Design": hot water 400 K, 3 atm, 1 kg/s; cold water 300 K, 1 atm, 2 kg/s; UA 2500 W/K; drops 10 and 5 kPa | independent UA-mode solution with CoolProp IAPWS-95 (both energy balances and Q = UA x LMTD with variable heat capacity), plus the tutorial's two published ranges |
| `water-exchanger-hot-outlet-specified` | same streams, hot outlet given as 80 C (my choice, flagged assumed) | energy balance only, no UA |
| `toluene-counter-current-exchanger-constructed` | all inputs mine (flagged assumed): toluene 150 C 10 bar 2 kg/s against toluene 30 C 5 bar 3 kg/s, UA 4000 W/K | independent UA-mode solution with CoolProp Toluene |

**Why no styrene/toluene FOSSEE Exp 10 case.** CoolProp has no styrene, so there is no independent reference, and the manual links the heater to the cooler's energy stream, which the IR cannot express. Exp 11 (shell-and-tube rating) needs geometry parameters that are not mapped.

**Results on the real server (24 runs, all solved, no findings, no mismatches; ledger 12, 6, 6 rows; hashes e05e00087b3b, 3c4795dfcb54, e5542bc41907).**
- Tutorial case, base: Steam Tables reproduces the independent solution to within 0.03 % on every value (hot out 86.13 C against 86.11, cold out 47.44 C against 47.44, duty 172.10 kW against 172.11); DWSIM's own LMTD (68.85 K) times UA gives its duty, so the mode behaves as documented. Scenarios: co-current (less heat, 165.5 kW, as expected), U doubled to 5000, cold flow doubled; all inside tolerance in Steam Tables. Peng-Robinson is 2 to 3 % and SRK 4 to 7 % off (the known cubic-equation weakness for liquid water, as in the heater cases). One published range failed for SRK only (cold outlet 36.59 C against a lower bound of 36.85 C in the doubled-cold-flow scenario; the range belongs to the base case).
- Outlet-specified case: Steam Tables within 0.03 %. In Peng-Robinson and SRK the cold outlet temperature is within 0.5 % while the duty is 9 % and 15 % off: both streams use the same package, so the error in water enthalpy cancels in the temperature and shows only in the duty.
- Toluene case: **the paper package (Peng-Robinson, an assumption) misses the tolerances fixed before the run: cold outlet +2.4 % against 2 %, duty +1.8 % (inside 3 %).** SRK is within them; Raoult's Law is not (hot outlet +3.0 %). I did not change the choice of paper package after seeing this.

Tests: `Exchanger` class, 5 tests (62 casebook tests): every validator rule fires, the tutorial reference satisfies Q = UA x LMTD with its own reported temperatures, the backend sends the mode, flow direction, U, area, pressure drops and ports, parallel flow transfers less than counter-current. A 6-mutant check on the new code: 6 caught. Not verified: a liquid-to-vapour exchanger, vapour-fraction outlet modes, and `cold_outlet_T` in a case.

Process note: I first launched the three ledger runs while a mutation check was editing the source files in the same working tree, so those 24 rows could have come from a mutated build. I deleted them and reran all three cleanly before recording the hashes above.

## 21. Design-criteria guardrails: OSHA, API, NFPA (built 2026-11-21)

Request: use the design criteria in API, OSHA and NFPA standards as guardrails for the simulations. What exists now, and the limit on what could be done honestly.

**Access.** OSHA's regulations are public and were fetched and read in full from osha.gov (29 CFR 1910.119 and 1910.106, 2026-11-21). The API and NFPA standards are sold, or free to read only behind a login; this tool does not use a login, so **no API or NFPA text was read and none of their numbers are built in.** Putting accumulation percentages or NFPA limits in from memory would be a guess presented as a standard, which the casebook forbids everywhere else. Those rules are registered as `paywalled-not-read` and activate only when the case supplies the numbers, with the clause and edition named, from a licensed copy.

**What a guardrail is.** `hysys_bridge/casebook/guardrails.py` plus the registry `studies/guardrails/rules.json`. After every solved run (each scenario and package) it checks the simulated streams and attaches rows `{rule, status, object, detail}` to the result, the CLI output and the ledger (non-pass rows only, as `rule:status:object`). Statuses: pass, violation, info, not-evaluated. A guardrail never changes a result, a tolerance or a published number (a test checks that the comparison values are identical with and without limits).

| Rule | Source | What it checks | Status |
|---|---|---|---|
| `osha-1910.119-d2iD-safe-limits` | 1910.119(d)(2)(i)(D): safe upper and lower limits for temperatures, pressures, flows or compositions | simulated stream T, P and mass flow against limits the case declares in `design_limits.streams` (with an anchor). The regulation sets no numbers; the limits are the process's own | active |
| `osha-1910.119-d2iE-deviation-coverage` | (d)(2)(i)(E) consequences of deviations; (f)(1)(ii) operating limits | a scenario (deviation) run in a case with no declared limits is reported not-evaluated: the deviation has no consequence criterion | active |
| `osha-1910.119-d3iG-material-balance` | (d)(3)(i)(G) material and energy balances | feed mass equals product mass in the simulated flowsheet; the 0.1 % tolerance is the tool's, not the regulation's (it sets none) | active |
| `osha-1910.106-a19-flammable-category` | 1910.106(a)(19)(i) to (v): categories 1 to 4 by flashpoint (23, 60, 93 C) and boiling point (35 C); liquids heated for use to within 30 F (16.7 C) of their flashpoint are handled as the next more hazardous category | needs flashpoint and boiling point per compound in `design_limits.compounds` (from a safety data sheet, with an anchor); applies to streams that are at least 99.9 % one such compound; reports the category and whether the simulated temperature triggers the heated-near-flashpoint rule (information, not a violation) | active when data given |
| `api-520-521-relief-overpressure` | API 520/521, ASME overpressure | stream pressure at a relief unit against set pressure x (1 + accumulation/100), both supplied by the user | paywalled, evaluates only with supplied numbers |
| `nfpa-30-flammable-liquids` | NFPA 30 and related codes | nothing | registered, no check |

**What it does not do.** It attaches no real design limits to any published case: limits are specific to a plant and none of the sources give them, so every existing case reports `not-evaluated` for the safe-limits rule. The flammable-category rule needs flashpoints I would otherwise take from memory; none are in the cases. The dynamic and consequence side of 1910.119 (relief sizing, fire cases, dispersion) is out of reach of a steady-state flowsheet and is not claimed.

**Live check.** On the tutorial exchanger with a synthetic 80 C limit on the hot outlet (marked synthetic in the case anchor), the real server gave a violation (86.13 C against max 80) in the base case and (87.7 C) in the co-current scenario, a passing material balance (10,800 kg/h in and out), and the flammable-category rule's information rows. The limit was not saved to any case file.

**Tests.** `Guardrails` class, 10 tests (72 casebook tests): registry statuses (only read or supplied rules are active), limits pass and violate on both sides, no limits is reported and not passed, material balance on both sides of 0.1 %, the OSHA category boundaries (22.9, 23, 60, 60.1, 93, 93.1 C and the 35 C boiling point), the 16.7 C rule at its boundary, relief numbers used only when supplied, 8 validation rules for `design_limits`, and the runner leaves comparisons untouched. A 10-mutant check: 9 caught; the survivor (activating paywalled rules) is equivalent today because the registered paywalled rules do not go through the active check.

**To extend it you can give me** (from your licensed copies): the clause, edition and numbers for any API or NFPA criterion you want enforced, or the plant's declared safe limits and compound flashpoints; each becomes a rule or a `design_limits` entry with its anchor.

## 22. Advisory guardrails from forum and trade discussion: vessels, pumps, valves (built 2026-11-21)

Request: use how vessel, pump and valve specification guidelines are openly discussed on forums. Section 21's rules come from regulations; these come from discussion, so they sit in a separate **advisory tier** of `studies/guardrails/rules.json`: they never produce a violation, only `advisory` or `info`, every rule lists its sources and how each was read, and disagreement between sources is stored with the rule.

**What I could read.** Searches (standard mode) found the discussions; each page was then fetched once, politely, with `fetch_source.py`. The forum hosts that matter most refused automated access with a bot challenge: **Eng-Tips and Cheresources returned challenges and were not retried or worked around**, so their content is known only from search-result summaries (second-hand) and the rules built on it are labelled `forum-snippet-only`. The Chemical Engineer's "Rules of Thumb" article (opening only; the rest is behind a login) and WaterWorld's NPSH-margin article (read in full from a Wayback copy after the live page challenged) were read directly. The Instrumentation Tools forum page is script-rendered and came back empty, so its figures are summary-only.

| Rule | What the discussion says | How read | Check on the simulation |
|---|---|---|---|
| `forum-vessel-design-pressure-margin` | design pressure at least maximum operating pressure plus the greater of 10 % or 25 psi (172.4 kPa); posters add it is owner preference, not set by ASME VIII; a "1.1 x or 30 psi" variant had no reference | summaries of Cheresources, Eng-Tips and a university process-design document (all second-hand) | design pressure (declared, with basis) against the simulated operating pressure converted to gauge. Assumption mine: the rule applies to gauge pressure |
| `forum-vessel-design-temperature-margin` | 15 to 20 C (SPE article), 28 C or 50 F (forum replies, university document); pipelines 10 C, exchangers 30 C; owner's judgement | summaries only | design temperature against the simulated operating temperature: pass at +27.8 C, advisory between +15 and +27.8, advisory below +15 |
| `pump-npsha-vs-npshr` | NPSHR is usually defined at a 3 % head drop | summary only | NPSHA = (suction pressure - vapour pressure) / (density x g) + static head, friction ignored; ratio below 1.0 is a **violation by definition**, not by a forum rule |
| `trade-pump-npsh-margin-ratio` | minimum NPSHA/NPSHR 1.0 to 1.3 (low suction energy), 1.1 to 1.5 (mitigating factors), 1.5 to 2.0 (cold or warm water), 2.0 to 2.5 (very high suction energy); reliability rises to a ratio near 4 | WaterWorld read in full (Wayback) | ratio against the range for the declared suction-energy class: below is advisory, inside is information, above passes. Other sources quote 1.2 to 1.6 and a fixed 1 m |
| `trade-valve-pressure-drop-fraction` | valve drop at least 20 % of the total system drop or 10 psi (0.7 bar), whichever greater; 30 %, 33 % and 50 % of friction drop also quoted on other bases; valves respond best 60 to 80 % open; rules of thumb are for preliminary selection only | The Chemical Engineer (opening read); others summary only | valve drop from the simulated inlet and outlet pressures against the declared total system drop: advisory below the 20 % / 0.7 bar rule, information below 33 % |
| `trade-valve-flashing` | liquid flashing across a valve needs a full flashing and cavitation calculation | summary only | outlet vapour fraction above the inlet's by more than 0.001 is reported as information |

**Not implemented, and why.** Valve opening (60 to 80 %) needs the valve position, which a steady-state flowsheet does not return. Pump operating range against best efficiency point needs the pump curve. Pump discharge design pressure from shutoff head: the sources disagree and say the governing piping code decides, so I did not turn it into a check. The 120 % figure that appears in a vendor blog is not used.

**Case inputs.** `design_limits.vessels`, `.pumps` and `.valves` (stream references, datasheet values with an anchor); validated with 9 rules. No published case carries any: they are specific to a plant. A live demonstration on the tutorial exchanger with clearly synthetic equipment data (not saved) produced the expected advisories on the real server (design 298.7 kPa(g) against 375 needed; temperature margin +13.1 C; NPSH ratio 2.01 passing; valve drop 10 % of a 100 kPa system drop).

**Tests and checks.** `Guardrails` class now 16 tests (78 casebook tests): registry provenance for every rule, the greater-of-10-percent-and-25-psi switch point in both directions and in both pressure bases, temperature bands and boundaries, NPSH ratio against each range plus static-head sign, valve fraction at and around the 20 % boundary and the 0.7 bar floor, flashing, no advisory rule ever returns a violation, nine validation rules. A 13-mutant check on the new logic: 13 caught. (A first run of that check reported 13 caught only because a bad edit had left a syntax error in the test file; I repaired the file and repeated the check, which is the result recorded here.)

**Weak points to keep in mind.** Most of the vessel and valve numbers rest on summaries of pages I could not open; the rules are advisories for that reason, and a rule's `sources` entry says exactly what was and was not read. If you can open the Eng-Tips and Cheresources threads yourself, the quickest upgrade is to paste the passages you trust and I will replace the summaries with what the posts actually say.

## 23. IIT Kharagpur course: what could be read, and cases 15 to 17 (pump, compressor, valve) (2026-11-21)

**The lectures could not be read.** NPTEL "Principles and Practices of Process Equipment and Plant Design" (103105210, IIT Kharagpur, Prof. Gargi Das and Prof. S. Ray, 64 lectures) is a video course. The course page (read from a Wayback copy; the live page is script-rendered) lists the lectures and says transcripts, assignments and books exist, but the page carries no file links. I tried the NPTEL naming pattern for the weekly assignment PDFs (weeks 8 to 11), the NOC archive path and the course preview page: none returned a document ("unavailable on every route"), and searches found no transcript. I did not go to YouTube captions or Scribd copies (terms of use and uncertain copyright). The companion book (Ray and Das, Elsevier 2020) is commercial. So **nothing of the lectures' content or numbers is used**, and the cases below do not come from them. What I did read is the lecture titles, which fix the topics: lectures 54 to 57 plant hydraulics (pumps, compressors, pipelines), 58 process vessels, 59 instrumentation, 60 engineered safety, 62 to 63 process design using simulators and process packages, 64 a 10 TPD mono-nitrotoluene plant design (a worked plant design whose content would be the most useful to read if its transcript can be reached).

**What I built instead.** Three constructed exercises on the course's week-10 equipment, every input mine and flagged assumed, each with an independent CoolProp reference, so that the DWSIM pump, compressor and valve are checked by value for the first time (before this, only their parameter mapping was verified):

| Case | Specification | Reference |
|---|---|---|
| `water-pump-constructed` | water 25 C, 36000 kg/h, 1 atm to 5 bar (scenarios: 20 bar, double flow) | isentropic enthalpy rise (IAPWS-95) divided by an efficiency of 0.75 |
| `methane-compressor-constructed` | methane 25 C, 3600 kg/h, 1 to 5 bar (scenario: 10 bar) | isentropic enthalpy rise (CoolProp methane) divided by 0.75 |
| `methane-valve-isenthalpic-constructed` | methane 25 C, 3600 kg/h, 50 bar to 20 bar (scenario: 30 bar) | constant-enthalpy expansion (real-gas Joule-Thomson) |

**Results on the real server (21 runs, all solved, no findings, no mismatches; ledger 9, 6, 6 rows; hashes 2156b5329aaa, 5c30b1f7acfc, 0fa407578673).**
- **Pump:** duty and outlet temperature within 0.3 % in Steam Tables, Peng-Robinson and SRK, in all three scenarios. The efficiency I assumed (0.75, from DWSIM's documented default) is confirmed by the match: the backend sends no efficiency, so the server's default is 75 %. A 0.039 K rise at 5 bar is too small for the temperature check to mean much; the duty is the real test.
- **Compressor:** duty and outlet temperature within 0.2 % in Peng-Robinson, SRK and Raoult's Law (an ideal gas is adequate for methane at 1 to 10 bar), both scenarios.
- **Valve:** the paper package (Peng-Robinson, my assumption) **misses the 5 % tolerance fixed before the run: outlet 10.5 C against the independent 11.99 C (-12.4 %), and 15.65 C against 16.56 C (-5.4 %) in the 30 bar scenario.** SRK is closer (-3.4 % and -1.4 %, inside tolerance). Raoult's Law gives 25 C: an ideal gas has no Joule-Thomson cooling, so it misses entirely (+108 %). I did not change the choice of paper package after seeing this. The CoolProp reference uses a reference-quality methane equation of state, so the cubic equations of state are the ones that differ, not the reference.

**Code change.** The validator used to require a temperature and a pressure on the outlet stream of a pump, valve or compressor as if both were specifications. The pressure is the specification; the temperature is a result. Now the outlet of a heater or cooler still needs its temperature, and a pump, valve or compressor outlet needs its pressure only (temperature optional). Tests: `PumpCompressorValve`, 4 tests (82 casebook tests): all cases validate with the new rule, a missing outlet pressure and a missing heater outlet temperature are both caught, the pump reference equals flow x pressure rise / (density x efficiency) to 0.2 %, and the signs and scaling of the compressor and valve references. A 3-mutant check of the rule: 3 caught.

**Weak points.** These are constructed exercises, not published ones: they test the simulator's pump, compressor and valve against physics, not against a source's answer key. The IIT Kharagpur plant-design lectures remain unread; if you can reach transcripts or the book, the simulator-based design lecture and the mono-nitrotoluene plant design are what to read first.

## 24. Three supplied documents: what each gave (2026-11-21)

The repository owner supplied three PDFs from a local folder. The review was read in full (6 pages). Of the polymer chapter (41 pages) I read pages 1 to 20; of the Aspen guide (99 pages) pages 1 to 8, 13 to 52 and 59 to 70 (60 pages). The long documents were read as page images, with two pages re-rendered at 260 dpi to confirm printed digits. None has a public address I verified, so the cases cite them by file name and SHA-256 (`source.local_copy`, a new accepted form of source identity next to doi and url). Both are copyrighted: only facts and numbers are used, no text or figures.

| Document | Gave | Not usable for |
|---|---|---|
| Jadhav, "Process Simulation and Optimization Using Aspen Plus: A Comprehensive Review", IJEDR 13(3), July 2025 (6 pages) | a qualitative survey (thermodynamic models, rice-bran-oil extraction, reactive distillation, CO2 capture with MEA, energy systems); no numbers, no worked example, nothing to check a simulation against | cases. Its reference list (13 items) was not verified, and I would not cite those items from this paper |
| Liu and Sharma (Virginia Tech, Aspen Technology), Chapter 1, "Introduction to Integrated Process Modeling, Advanced Control, and Data Analytics in Optimizing Polyolefin Manufacturing" (2023, 41 pages) | printed worked numbers for polymer stream initialisation (Table 1.2), a hand example with chains of 3, 4 and 5 segments, and a printed sensitivity table of a copolymer mixing workshop (Figure 1.20) | the HDPE slurry workshop: its results are not in the pages read |
| AspenTech, "Aspen Plus: Getting Started Building and Running a Process Model", version 2006.5, November 2007 (99 pages) | printed results for a methanol/water flash (chapter 1), a 22-stage extractive distillation column for methylcyclohexane with phenol (chapters 2 to 4: stream and block results, a sensitivity table and a design-specification result) | chapters 5 to 7 (flowsheet drawing, estimating thiazole properties, a Txy diagram) were not read for numbers; chapter 8 is connection setup |

### 24.1 Polymer moments: a calculator checked against the chapter (`hysys_bridge/polymer_link.py`, tools `polymer_stream_attributes` and `polymer_mix`)
Pure arithmetic of the method of moments that Aspen Polymers uses (ZMOM, FMOM, SMOM, DPN, DPW, PDI, MWN, MWW, additive when streams mix). It refuses MWW below MWN, since PDI below 1 is impossible by definition. The module reproduces the printed numbers: the toy chain example (DPN 4, DPW 4.17, PDI 1.04) and Table 1.2 (MWSEG 51.266, DPN 390.12, DPW 1755.55, ZMOM 5e-5, FMOM 0.019506, SMOM 34.2438, segment flows 0.011704 and 0.007802 kmol/s) to 1e-5.

**A finding in the printed workshop table.** The chapter's workshop 1.1 mixes EVA80 (MWN 2,000, MWW 5,000) with EVA50 (MWN 20,000, MWW 50,000) and prints MWN, MWW and PDI against the EVA80 flow (Figure 1.20; I confirmed the digits at 260 dpi). The printed MWN agrees with exact mixing in all 11 rows (to 1e-5). **The printed MWW and PDI cannot come from the stated inputs**: for equal flows the printed MWW is 3480.94, which is below the printed MWN of 3636.36, and the printed PDI is 0.957, below 1 in every row. With both streams entered as stated, exact mixing gives MWW 20,291 and PDI 5.58 for the equal-flow row. The printed MWW and PDI are reproduced to 0.02 % in all 11 rows if EVA50 carries a zero second moment (its MWW not entered). That is consistent with an omitted input, and the chapter's own plot of MWW falling to about zero at pure EVA50 points the same way, but it is an inference, not something the chapter says. A mixed MWW also differs from the mass-weighted average of the inputs when their segment compositions differ (my derivation from the chapter's definitions; with equal segment composition it is the mass-weighted blend). Tests: `test_polymer_link.py` (10 tests; a 9-mutant check, 9 caught after one boundary test was added).

### 24.2 Aspen Getting Started flash: case `methanol-water-adiabatic-flash-aspen-getting-started`
Feed 50 lbmol/h methanol and 50 lbmol/h water at 180 F and 20 psia, adiabatic flash at 1 atm. Printed: 165.28321 F, vapour fraction 0.10756625, vapour 10.757 lbmol/h (8.262 methanol, 2.494 water) and 309.677 lb/h. Molar masses 32.042 and 18.015 reproduce the printed vapour mass flow to 0.005 %. The guide never states the property method of this example (its template says "Property Method: None"), so the case records the paper package as "not stated" and `paper_package_within_tol` is now `None` in that situation (it used to read `False`, which would have meant a failure).

**Result on the real server (5 packages, ledger 5 rows, hash 0ca43bdb17dc), tolerances fixed before the run.** Flash temperature: NRTL 74.19 C and Peng-Robinson 74.18 C against the printed 74.05 C (+0.2 %), SRK +0.9 %, Raoult's Law +4.0 %, UNIQUAC +8.8 %. **Vapour fraction matches no package**: printed 0.108 against NRTL 0.181, Peng-Robinson 0.064, SRK 0.021, Raoult 0.014, UNIQUAC 0.004. The vapour methanol fraction is within 2 % in every package. So the temperature points to a model close to NRTL or Peng-Robinson, but the vapour fraction (a quantity that depends strongly on the enthalpy model for an adiabatic flash) does not agree with any of them; I cannot identify Aspen's method from this.

### 24.3 Aspen Getting Started extractive distillation: case `mch-extractive-distillation-aspen-getting-started` (status `blocked`)
Methylcyclohexane and toluene (200 lbmol/h each, 220 F, 20 psia) with 1200 lbmol/h phenol solvent, a 22-stage column, reflux ratio 8, distillate 200 lbmol/h, UNIFAC. Recorded as an answer key: stream 3 (distillate) composition and mass flow (19605.002 lb/h, which the molar masses reproduce to 0.0005 %), and the chapter 3 sensitivity table of MCH purity against phenol flow, 1200 to 2000 lbmol/h (0.97257198 rising to 0.98633569), as nine runs. It cannot run: no backend here has a verified rigorous column (`column` is an unverified unit type; the DWSIM server could not take a feed stage, architecture doc section 13). `run_case` refuses it and says why.
**Two answers in the guide disagree.** The design-specification result table prints a phenol flow of 1515.07763 lbmol/h (I confirmed the digits at 260 dpi) while the text beside it says approximately 1517.1; linear interpolation of the guide's own sensitivity table to 98.0 % purity gives 1516.9. Both are recorded in the case note; the table value is not preferred over the text.

### Code changes
New reference kind `stream_mole_fraction` (DWSIM returns mass fractions; the case's molar masses convert them; a case using it must list molar masses for every compound; tested end to end against the flash fake). `source.local_copy` {filename, sha256, supplied_by} accepted when a document has no doi or url. `paper_package_within_tol` is `None` when the source names no package. Tests: `AspenGettingStarted` class, 8 tests (90 casebook tests); a 7-mutant check on the runner and validator changes, 7 caught after one end-to-end test was added.

### Other open leads
University-hosted copies of the Aspen Plus "Getting Started" guides exist at other versions (a V8.4 copy at zakrzewska.zut.edu.pl, a V10 copy at chbe.umd.edu, 2004.1 petroleum and equation-oriented guides at the University of Alberta, an Aspen Plus tutorial at IIT Guwahati); I did not open them, and whether their printed numbers match the 2006.5 guide is unknown. The Liu and Sharma book chapters are on engrXiv (preprints 3843 and 4402 to 4406 appeared in a search); I did not open them, and the HDPE slurry workshop results are the next numbers worth checking.

## 25. The HDPE slurry workshop on engrXiv (opened 2026-11-21)

**Where it is.** The chapter is on engrXiv as preprint 4406, doi 10.31224/4406 (https://engrxiv.org/preprint/view/4406), posted 2025-02-26 by Niket Sharma and Y. A. Liu (Virginia Tech), **licensed Creative Commons Attribution 4.0** (read on the landing page). That is a better licence position than the Aspen guide: numbers and structure can be reused with attribution. The landing page was fetched once; I did not download the engrXiv PDF (a file download) but read the supplied copy, which carries the same title and the same "preprint version of a chapter" statement; I did not compare the two page by page. The workshop is section 1.3 (supplied-PDF pages 17 to 26): a simplified slurry HDPE process, a Ziegler-Natta RCSTR followed by a flash, built in 13 steps. The same book's other chapters are also on engrXiv (preprints 3843, 4402, 4403 and 4404: chapters 7, 6, 5 and 3), not opened. `polymer_link.py` and its tests now cite the doi.

**What it prints.** Only the open-loop result (step 10, Figures 1.40 and 1.41): feeds C2 (5700 kg/h ethylene, 40 C, 1300 kPa), CAT (255.31 kg/h: TiCl4 1.22, TEAL 1.16, hexane 252.93; 20 C, 700 kPa), H2 (8 kg/h, 25 C) and HX (15000 kg/h hexane, 40 C, 1400 kPa), and the POLYMER stream (20875.2 kg/h, 85 C, 755 kPa; ethylene 11.9272, HDPE 5684.82, TiCl4 1.22, TEAL 0.927715, H2 1.99774, hexane 15174.3; DPN 99598.2, DPW 254569, FMOM 202.632 kmol/h). The VAPOR stream is not printed. Step 11 gives two scalar results from the text: ethylene conversion 5684.82/5700 = 99.73 % with MWN 2.794E6 and MWW 7.194163E6, and after reducing every chain-propagation pre-exponential factor tenfold, 5525.38/5700, MWN 2.71533E6 and MWW 6.94027E6. The closed loop, the data fit and the design specification are in chapter 5, not here; the dynamic model is chapter 7.

**Case `hdpe-slurry-open-loop-liu-sharma`, status `blocked`.** It cannot run: an RCSTR with 70 Ziegler-Natta reactions on five catalyst sites, the POLYSL equation of state and polymer attributes exists in no backend here (`reactor` is an unverified unit type and no kinetic reaction tool exists on the DWSIM server, see section 19). It records the feeds and the printed POLYMER stream as an answer key (temperature, pressure, mass flow, five mass fractions), with the digits confirmed at 300 dpi.

**Checks of the printed numbers (tests `HdpeSlurry`, 6 tests).**
- The printed polymer components add to the printed stream flow (20875.19 against 20875.2); the catalyst components add to 255.31.
- Feeds total 20963.31 kg/h, so the unprinted vapour stream carries 88.11 kg/h; the component deficits in the polymer stream (ethylene 3.253, hydrogen 6.002, hexane 78.63, TEAL 0.232) add to 88.117, within 0.02 %. So the printed numbers close a mass balance.
- FMOM equals the HDPE mass over the ethylene segment mass (28.0538), and DPN times that mass gives the text's MWN, both within 0.02 %.
- **Two slips in the text, both inferences from arithmetic.** (1) The first run's MWW is printed as 7.194163E6, but DPW times the segment mass gives 7.1416E6, 0.73 % lower; the second run's printed MWN and MWW give a PDI of 2.556, the same as the table's DPW/DPN, while the first run's text values give 2.575. A transposed digit (7.141163E6 for 7.194163E6) would agree to 0.01 %. (2) The second run's conversion is printed as 97.94 %; 5525.38/5700 is 96.94 %.
Neither changes anything the repository computes; they are recorded so nobody tunes a model to match a misprint. Together with section 24 (the printed MWW and PDI of workshop 1.1 do not follow from the stated inputs), this chapter now has three places where a printed number disagrees with its own arithmetic.
