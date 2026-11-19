# Tools and papers for an LLM process-simulator copilot (research notes, 2026-11-20)

Source: web searches plus the GitHub API for repo metadata. Repo READMEs and tool lists were NOT opened unless stated, and no
code was run from these repos. Licences below are what the GitHub API reported; where it said none, treat as unlicensed.

## Existing MCP servers (candidates to call, not vendor)

| Simulator | Repo | Licence (API) | Pushed | Notes |
|---|---|---|---|---|
| Aspen Plus | [brack101/AspenPlus-MCP-Server](https://github.com/brack101/AspenPlus-MCP-Server) | none reported (directory listings say MIT) | 2026-11-18 | 38 stars, pywin32 COM, Windows only. Already cited in `mcp_server.py`. Confirm the licence before borrowing anything. |
| Aspen Plus V15 | [Eduardo-Mariola/aspen-plus-mcp](https://github.com/Eduardo-Mariola/aspen-plus-mcp) | MIT | 2026-10-23 | RadFrac column internals; fastmcp + pywin32. |
| Aspen Plus V15 | [thirakorn-mokkawes-59/aspen-mcp](https://github.com/thirakorn-mokkawes-59/aspen-mcp) | MIT | 2026-06-07 | Says 85 tools over COM. |
| Aspen Plus | [ddtlxc001/aspen-mcp](https://github.com/ddtlxc001/aspen-mcp) | MIT | 2026-06-29 | Python MCP server. |
| DWSIM | official `dwsim-mcp` (ghcr.io/danwbr/dwsim-mcp), source in [DanWBR/dwsim10](https://github.com/DanWBR/dwsim10) | GPL-3.0 | 2026-11-19 | Used here, verified. Call it as a separate process; do not copy its code into a differently licensed repo. |
| DWSIM | [OntoLedgy/ol_dwsim_interop_services](https://github.com/OntoLedgy/ol_dwsim_interop_services) | AGPL-3.0 | 2026-08-25 | Different tool names; call only, never vendor. |
| DWSIM | [josemacontrerasp-arch/bobprompter-dwsim-mcp](https://github.com/josemacontrerasp-arch/bobprompter-dwsim-mcp) | none | 2026-05-02 | Unlicensed: read for ideas only. |

Gap: no vendor-published Aspen Plus MCP server; the COM interface is poorly documented, so a node-path catalogue
(see ASPEN_PLUS_COPILOT_DESIGN.md) is the work to do. Best next move: read the Eduardo-Mariola and thirakorn READMEs for
tool lists and node paths (MIT, so reusable with attribution), then test on a licensed Windows host.

## Papers, grouped by what they give the build

**Agents driving a simulator**
- [Liang, Groll, Sin, arXiv 2601.11650](https://arxiv.org/abs/2601.11650): MCP + AVEVA Process Simulation; documents the failure modes our guardrails target.
- [Tian, Du et al., From Text to Simulation, arXiv 2601.06776](https://arxiv.org/abs/2601.06776) (AAAI-26): four agents (task, topology, parameters, evaluation) + MCTS; reports +31.1% convergence rate and -89% design time on the Simona dataset.
- [Context is all you need, AIChE J.](https://www.citedrive.com/en/discovery/context-is-all-you-need-toward-autonomous-modelbased-process-design-using-agentic-ai-in-flowsheet-simulations/) (DOI 10.1002/aic.70488): agentic flowsheet design.
- BASF Chemasim agentic study (AIChE 2026): copy previous results as initial guesses for convergence; cannot rescue fundamentally flawed plans.

**Diagram and document to flowsheet**
- [Sketch2Simulation, arXiv 2603.24629](https://arxiv.org/abs/2603.24629): diagram to executable HYSYS; connection consistency above 0.93, stream above 0.96; recycles are the weak spot.
- [Text-to-flowsheet, Digital Discovery 2026](https://pubs.rsc.org/en/content/articlehtml/2026/dd/d6dd00060f): Aspen Plus, black-box optimisation fills missing data.
- [From P&ID Drawings to Process Graphs, arXiv 2607.19568](https://arxiv.org/abs/2607.19568): multimodal LLM P&ID to graph (venue not checked).
- [ChatP&ID / GraphRAG for engineering diagrams, AIChE J.](https://www.citedrive.com/en/discovery/scpgraphragscp-for-engineering-diagrams-scpchatpscp-amp-scpidscp-enables-scpllmscp-inte/) (DOI 10.1002/aic.70540): DEXPI to knowledge graph; reports +18% accuracy and -85% tokens versus images.
- [PID2Graph, arXiv 2411.13929](https://arxiv.org/abs/2411.13929): public P&ID graph dataset (our `pid_eval` already notes it is not comparable).

**Other**
- Politecnico di Milano thesis: natural language to HYSYS/DWSIM XML; DWSIM's XML was harder to generate.
- GRICU 2025 (de Fusco, Vallerio, Manenti): fine-tuned LLM generating Aspen models.
- Target paper (ACS IECR 65(31) 16718): only the IChemE webinar abstract was found.

## What this changes for the build

1. Do not write a COM layer from scratch: study two MIT Aspen MCP servers first.
2. Add an evaluation harness modelled on Simona (convergence rate, design time) and Sketch2Simulation (connection/stream consistency); we already have `pid_eval`.
3. Add a "reuse previous solution as initial guess" step to the solve path (Chemasim finding), and a recycle-aware test, since recycles are where both Sketch2Simulation and Chemasim struggle.
4. Feed P&ID/DEXPI through a knowledge-graph view (ChatP&ID) rather than raw images; our DEXPI export already makes this possible.
5. Unchecked: Simona dataset availability and licence; whether any paper released code.

## Read 2026-11-20: the two MIT Aspen Plus MCP servers (README + source, not run)

Fetched from GitHub via raw files into a scratch folder; nothing executed. Both are MIT. `Eduardo-Mariola/aspen-plus-mcp` credits
"original aspen-mcp code" in its LICENSE and has near-identical source to `thirakorn-mokkawes-59/aspen-mcp`, so treat them as one
lineage; Eduardo's adds Column Internals (a `tools/internals.py`) and is the newer. Windows only, Aspen Plus V15 (GUI 41.0),
pywin32 + fastmcp. Claims of working runs are the author's own (a benzyl-alcohol plant); none were reproduced here.

**COM calls, now corroborated by independent working code** (this resolves most of section 6 of the design doc):
- `win32com.client.Dispatch("Apwn.Document")`; set `SuppressDialogs = True` on connect or modal dialogs hang the server.
- Open `.apw/.apwz` with `InitFromFile2`, `.bkp` with `InitFromArchive2` (using Archive on an `.apw` leaves `\Data\Blocks` empty).
- Nodes: `app.RootModel("").FindNode(r"\Data\Streams\S1\Input\TEMP\MIXED")`, `.Value`, `.SetValue(0, value)`, `.Elements` / `InsertRow`.
  Correction to my design doc: the tree root is `RootModel("")`, not `Tree`.
- Run: `Engine.Run2(True)` asynchronous, poll `Engine.IsRunning`, `Engine.Stop()`; `Reinit()`; `SaveAs(path)`; `Visible`.
- All COM calls run on one dedicated STA thread (`pythoncom.CoInitialize()`); the server also attaches to a simulation already open
  in the GUI and, if DCOM cannot start Aspen on a small machine, launches `AspenPlus.exe` and attaches.
- Stream composition: one node, `\Data\Streams\{name}\Input\FLOW\MIXED\{component}`; its BASIS attribute (`MOLE-FLOW`, `MASS-FLOW`,
  `MOLE-FRAC`, `MASS-FRAC`) sets the meaning, and fraction bases also need a total flow.
- Block inputs/outputs, e.g. Flash2: `\Data\Blocks\{n}\Input\TEMP|PRES|DUTY|VFRAC`, results `\Data\Blocks\{n}\Output\B_TEMP|B_PRES|B_VFRAC|QCALC`.

**Reusable assets (MIT, keep the copyright notice):**
- `docs/blocks/*.md`: about 35 block types, each with ports, input paths and output paths: a ready-made seed for our node-path catalogue.
- `knowledge/convergence.py`: seven failure modes (tear-stream, bad initial guess, ...) with symptoms, checks and fixes: a ready seed for the "skills" layer.
- Tool surface worth mirroring: open/attach/run/reinit_and_run/save, get/set by path, add_block/connect_port, set_property_method, diagnose,
  incomplete-input scan, tear streams, sensitivity.

**Gaps relative to our design:** no write gating (no confirm, no named-case rule that I saw), no validation against an H&MB or P&ID, no
degrees-of-freedom pre-check before running, no evaluation harness, no mock backend (so no CI without a licence). Those are exactly what
`hysys_bridge` adds, so the plan is: use their COM patterns and block docs, keep our gates.

**Recommended build step:** an `AspenPlusCOM` backend implementing our Backend protocol using the calls above (STA thread, SuppressDialogs,
RootModel/FindNode), a catalogue generated from their `docs/blocks`, and a `MockAspen` that replays recorded node values. Still needs a
licensed Windows host to test: none of this can run on this Mac.
