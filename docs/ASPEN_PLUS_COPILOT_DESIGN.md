# Aspen Plus copilot on top of process-sim-bridge — design draft

Status: DRAFT, 2026-11-20. Nothing here is implemented or run against Aspen Plus.
Reference paper: LLM-Powered Copilot for Aspen Plus (Ind. Eng. Chem. Res. 65(31), 16718). Only the webinar abstract was
read (Claude + MCP, 42 tools, a "Skills" knowledge layer, engineer stays decision-maker); the paper text was not.

## 1. What already exists here (hysys_bridge)

| Piece | File | Reuse for Aspen Plus |
|---|---|---|
| Flowsheet IR (units, streams, SPEC vs CHECK values, provenance) | `ir.py` | As is. Backend-neutral. |
| Backend protocol (`new_case/add_stream/add_unit/connect/set/get/solve`) | `backend.py` | Add `AspenPlusCOM` + reuse `MockHysys` as a generic mock. |
| Validation, H&MB check, read-back audit | `validate.py`, `hmb_check.py`, `hysys_writer.py` | As is. |
| Gated writes (confirm, env flag, named case, never saves) | `mcp_server.py` | Keep the policy; copy the pattern. |
| JSON-RPC stdio loop, tool table with strict schemas | `mcp_server.py` | Keep; split Aspen tools into a second module. |
| P&ID / DEXPI / H&MB loaders | `pid_*.py`, `dexpi_*.py`, `extract_hmb.py` | Input side, unchanged. |

Prior art noted in the `mcp_server.py` docstring: `brack101/AspenPlus-MCP-Server` (MIT). Read it first and decide
whether to call it, contribute to it, or only borrow its COM node paths. Do not vendor code without checking its licence.

## 2. Gaps versus the paper's copilot

1. **Aspen Plus has a variable tree, not an object model.** HYSYS is driven through typed COM objects; Aspen Plus through
   `Tree.FindNode(r"\Data\Streams\S1\Input\TEMP\MIXED").Value`. The copilot needs a *node-path catalogue*, not hard-coded
   attribute names.
2. **Convergence and input-completeness feedback.** The Liang/Groll/Sin AVEVA paper (arXiv 2601.11650) reports the agent
   setting unspecified variables and tuning too early. Aspen exposes block/stream status and error/warning history; the
   server must return these structured after every run.
3. **Knowledge layer ("Skills").** Property-method selection, column initialisation, convergence recipes. Not in the bridge.
4. **Bulk reads.** An LLM should ask "give me all stream results as a table", not 200 single-node calls.

## 3. Proposed architecture

```
Claude / MCP client
   |  stdio JSON-RPC
aspen_mcp (new, hysys_bridge/aspen/server.py)        <- same gating policy as hysys_bridge.mcp_server
   |-- session store: Flowsheet IR (reused)
   |-- AspenPlusCOM backend  (Windows only, `Apwn.Document`)   [UNVERIFIED names, see section 6]
   |-- MockAspen backend     (any OS; tests, dry runs)
   |-- catalogue/            node-path maps: block type -> required inputs -> result nodes (JSON, versioned)
   |-- skills/               markdown playbooks surfaced as MCP resources (not tools)
   '-- guardrails.py         spec-completeness, DOF check, run-status parser
```

### Tool set (about 20, grouped; the paper's 42 is not copied, only its shape)

Read-only (no gate):
- `aspen_status` — platform, COM available, live flag, open case, engine version.
- `list_blocks`, `list_streams`, `list_components`, `get_property_method`.
- `get_node(path)` and `get_results_table(kind=streams|blocks, fields=[...])` — bulk, returns units with every value.
- `get_run_status` — convergence flag, per-block status, errors and warnings text, iteration counts.
- `check_specs` — degrees-of-freedom / unspecified-input report per block *before* any run.
- `describe_block_type(type)` — from the catalogue: required inputs, typical ranges, result nodes.

Write (every one needs `confirm=true`, live needs `ASPEN_LIVE=1`, named `case_path` or `use_active`, no save):
- `build_from_session(name)` — IR to Aspen via backend protocol (streams, blocks, connections, fluid package).
- `set_node(path, value, unit)` — single edit; refuses paths outside the catalogue unless `allow_raw=true`.
- `run_simulation(timeout_s)` — `Engine.Run2`-style; always returns the structured `get_run_status` payload.
- `reinitialize(scope)` — reset a block or the whole case (gated separately; destroys convergence state).
- `sensitivity(var_path, values, observe_paths)` — loops set, run, read; capped at N points; restores the base value.

Analysis (pure Python, reuse existing code):
- `compare_to_hmb` (existing `hmb_check`), `mass_balance`, `export_flowsheet_json`.

### Guardrails (the part that answers the AVEVA failure modes)

- **Plan, then apply.** Model proposes an edit list; server validates it against the catalogue and returns a diff;
  only then `apply_plan(confirm=true)`. No free-form `set_node` chains by default.
- **Spec-completeness gate.** `run_simulation` refuses while `check_specs` reports an unspecified required input, and
  names the missing node paths. This directly targets "set unspecified variables / premature parameter tuning".
- **One change per run in tuning mode.** Server records every edit and result in an audit CSV (already how `hysys_writer`
  works), so the engineer can replay or revert.
- **Everything comes back with units and provenance.** No bare floats.
- **Skills as resources.** Property-method choice, column start-up, convergence ladder (sequential-modular tear settings,
  damping, reinitialise) as short markdown with source citations; the model reads them, the server does not enforce them.
- **Human-in-the-loop:** write tools return a plan card by default; the live path requires the same three conditions as the
  HYSYS tools. The copilot never saves or overwrites a `.bkp/.apw` file.

## 4. Build order

1. `MockAspen` backend and the catalogue schema; port the existing mock tests. Runs on this Mac.
2. Read-only tools against a real Aspen Plus install on a Windows machine (status, lists, `get_node`, results tables).
   This is the first point where the COM paths get verified.
3. `check_specs` + `run_simulation` with structured status.
4. `build_from_session` for the unit types the IR already knows (mixer, splitter, pump, heater, cooler, valve, separator),
   then RadFrac/Flash/Reactor via the catalogue.
5. Skills resources and an eval set (below).
6. DWSIM backend through its MCP server as an open-source rehearsal target, so the logic can be tested without a licence.

## 5. Evaluation (do not skip; the paper-class claims need it)

- Reuse `pid_eval.score` for topology. Add convergence rate, number of runs to convergence, and result deviation versus a
  hand-built reference case, on 10–20 textbook flowsheets (flash, distillation, reactor-separator, heat-exchanger network).
- Report failure cases (unspecified-input writes blocked, wrong property method chosen), not only success rate.
- Track which skill documents were read per run, so a skill's effect can be measured.

## 6. Unverified assumptions (verify before trusting any write)

- ProgID `Apwn.Document`, `InitFromArchive2` / `InitFromTemplate2`, `Tree.FindNode`, `.Value`, `Engine.Run2`, and
  run-status node paths are recalled from Aspen's automation documentation, not checked here. The same caveat already
  applies to the HYSYS COM code in `backend.py`.
- Unit handling in node writes (`.Value` plus a separate unit attribute) differs by node; the backend must set and read back
  units explicitly, as `hysys_writer` does.
- Licence: automation needs a licensed Aspen Plus install; the server only runs live on that Windows host.

## 7. Open questions for the owner

1. Is an Aspen Plus licence available (host, version)? If not, step 6 (DWSIM) becomes the main target.
2. Keep one server with both simulators, or a separate `aspen_mcp` module? Recommendation: separate module, shared IR and gates.
3. Is `brack101/AspenPlus-MCP-Server` acceptable as a dependency, or should the COM layer be written fresh?

## 8. Update 2026-11-20: DWSIM rehearsal backend built (instead of a generic mock)

Per the owner ("use dwsim"), step 1 became `hysys_bridge/dwsim/`: a `DwsimBackend` (same Backend protocol as HYSYS) that
talks to DWSIM's MCP server, a `FakeDwsim` transport, and a backend-neutral `check_specs` guardrail. 5 tests pass; the
72 existing tests still pass. DWSIM is not installed here, so nothing has run against the real server. Only 3 tool names
(`dwsim.flowsheet.create`, `dwsim.thermo.add_compounds`, `dwsim.unitop.add`) are confirmed from DWSIM's tutorial; the rest are
guesses held in `backend.TOOLS` with a `verified` flag. Not yet wired into `mcp_server.py` tools.

### 8.1 Verification result (2026-11-20, against DWSIM's published tutorials, not a running server)

Corrected from the docs: every call but `flowsheet.create` needs `flowsheet_id`; `add_compounds` takes `names`; there is a
`thermo.set_property_package` and the solve tool is `dwsim.solve.run` (my earlier `dwsim.flowsheet.solve` was wrong);
`dwsim.stream.add_material` creates a stream with its values in one call; Heater/Cooler take `outlet_temperature_K`,
`pressure_drop_Pa`, `efficiency_percent` on `unitop.add`. Still unknown: `unitop.connect` argument names, the `solve.run`
response shape, and **any tool to read results or edit a stream afterwards**. Until a results tool is found the backend
cannot do the H&MB comparison, and its read-back is local only (`readback_is_local`). Next: install DWSIM + its MCP server
(needs your OK to download) and run `tools/list`, which settles all of this. A PyPI package `ol-dwsim-mcp-server` (OntoLedgy,
different tool names, AGPL per earlier notes) also exists; pypi.org served a bot challenge, so it was not read.

### 8.2 Live verification (2026-11-20, real server)

Ran `ghcr.io/danwbr/dwsim-mcp:latest` (dwsim-mcp-server 1.0.0, 58 tools, `--stdio`, `--network none`, via podman) and the
backend against it: a pump + heater water flowsheet builds, passes the server's degrees-of-freedom check, solves, and
`stream_get_results` returns exactly the specified T, P and flow (opt-in test `test_dwsim_live.py`). This **supersedes 8.1**:
tool names are underscored (`dwsim_*`, not dotted), property packages are full names ("Peng-Robinson (PR)"), compositions are MASS
fractions, connect is one stream per call, and results/DOF/check/scenario tools **do** exist. Still unverified: valve,
compressor, splitter, vessel property names; mixed multi-component and recycle flowsheets; the Patreon-only components need
a licence key. Design consequence: the server already ships spec-completeness (`dwsim_flowsheet_degrees_of_freedom`,
`dwsim_flowsheet_check`) and explanation tools, so our value-add is the IR/H&MB/P&ID front end, the plan-then-apply gate and
the evaluation harness, not re-implementing those.

### 8.3 MCP tools wired (2026-11-20)

`hysys_bridge/dwsim/tools.py` registers six tools into `hysys_bridge.mcp_server`: `dwsim_status`, `dwsim_check_specs`,
`dwsim_build` (confirm=true; mock unless `live=true` and the operator sets `DWSIM_MCP_CMD`), `dwsim_solve` (blocked while DOF
are open; compares results with specs), `dwsim_read_stream`, `dwsim_close`. Tests: 7 mock-backed, plus a live round trip through
the tools against the real server (`DWSIM_MCP_LIVE=1`). Not yet: sensitivity sweep, plan-then-apply edit list, scenario tools.

### 8.4 Aspen Plus backend + catalogue (2026-11-20, untested on Aspen)

`hysys_bridge/aspen/`: `catalogue.py` (block models, ports, node paths, unit tables; each entry marked `doc` or `guess`; seeded from the two
MIT servers' block docs, attribution in the file), `backend.py` (`AspenBackend` on the Backend protocol over a path `Tree`; `MockTree`
for CI; `AspenComTree` for Windows, never run), 12 tests on the mock. Design choices: every write reads the node's `UnitString` and
converts or refuses (no unit guessing; a mass spec onto a mole-flow node is an error); derived-stream specs go onto block inputs at
solve; valve and compressor are refused unless `allow_unverified=True` (their inputs are not documented in the sources);
only T and P results are readable (the only documented result paths). Not done: MCP tools for Aspen, the property-method name map beyond
Peng-Robinson, recycles/tear streams, columns. First job on a licensed Windows host: run `AspenComTree` against a blank case and fix
whatever the `guess` entries got wrong (pump model string, total-flow node `TOTAL` vs `TOTFLOW`, run-status nodes).
