# Research: LLMs for HAZOP / HAZID, and testbeds for process models (2026-11-20)

Evidence level: **[checked]** = title, authors, date and abstract read through the arXiv API; **[snippet]** = taken from a search-result snippet only, not opened.
No paper below was run or reproduced.

## 1. LLMs for HAZOP / HAZID / hazard identification
| Paper | What it gives | Level |
|---|---|---|
| [Talking like P&IDs, arXiv 2502.18928](https://arxiv.org/abs/2502.18928) (Alimin, Goldstein, Schulze Balhorn et al., Feb 2025) | DEXPI P&IDs as labelled property graphs queried by an LLM; lists AI-assisted HAZOP as next step | [checked] |
| [GraphRAG for Engineering Diagrams: ChatP&ID, arXiv 2603.22528](https://arxiv.org/abs/2603.22528) (Alimin, Schweidtmann, Mar 2026) | GraphRAG over smart P&IDs; benchmark in which ContextRAG reached 91% at about $0.004 per query (GPT-5-mini); AIChE J. DOI 10.1002/aic.70540 | [checked] abstract; figures from snippet |
| [The Competence Shadow: Theory and Bounds of AI Assistance in Safety Engineering, arXiv 2603.25197](https://arxiv.org/abs/2603.25197) (Siddique, Mar 2026) | Formal framework for when AI assistance helps or hides blind spots in safety analysis; useful for designing the evaluation | [checked] abstract |
| "Can large language models automate the HAZOP process without human intervention?" (Safety Science, 2026, KFUPM) ([record](https://pure.kfupm.edu.sa/en/publications/can-large-language-models-automate-the-hazop-process-without-huma/)) | Four multimodal LLMs wrote HAZOP worksheets from one P&ID, scored against an expert reference; F1 above 86% but semantically valid scenarios only 0.19 to 0.37 | [snippet] |
| Liang et al., NPCW 2026 ([PDF](https://npcw2026.compute.dtu.dk/Liang_npcw2026.pdf)) | Multi-step LLM workflow for deviations, causes, consequences, safeguards, recommendations; notes ground-truth HAZOPs are scarce | [snippet] |
| "AI-assisted HAZOP: can prompt engineering deliver a credible HAZOP assessment" (SCSC) ([record](https://scsc.uk/resources/citation_r3344.html)) | Multi-step, chain-of-thought and few-shot prompting on a water-production system, expert-reviewed | [snippet] |
| SIGDIAL 2026 paper 1.53 ([PDF](https://aclanthology.org/2026.sigdial-1.53.pdf)) | Proposer/Critic debate vs cooperative multi-agent hazard identification against single-pass baselines | [snippet] |

Takeaway: results are small-scale and judged by experts; all report that **plausible-looking but invalid scenarios** are the failure mode. A simulator is the missing ground truth.

## 2. Simulation-based hazard identification (the ground-truth side)
- [DTU: a simulation-based engineering method to support HAZOP studies](https://orbit.dtu.dk/en/publications/a-simulation-based-engineering-method-to-support-hazop-studies/): systematic failure scenarios from equipment deviations, evaluated in a dynamic simulator (K-Spice, gas reinjection), ranked by criticality [snippet].
- [Software tool for hazard identification from process simulation (CET)](https://cetjournal.it/index.php/cet/article/view/10087): built on Aspen HYSYS; parametric sensitivity with runaway and steady-state multiplicity detection, on ammonia synthesis and propylene glycol [snippet].
- [LOPA and HAZOP concepts for automated hazard identification (CET)](https://cetjournal.it/index.php/cet/article/view/10163): protection layers tested with dynamic simulations of failures [snippet].
- [Toward HAZOP 4.0, polymerisation reactor (TU Dresden)](https://fis.tu-dresden.de/portal/de/publications/toward-hazop-40-approach-for-managing-the-complexities-of-the-hazard-and-operability-of-an-industrial-polymerization-reactor(752e90dd-d54d-47f7-b321-bcae96469fc8).html): multiple failures and domino effects with dynamic simulation [snippet].
These are older (2012 to 2019) and mostly one research group; no digital-twin paper was found.

## 3. Testbeds where models and agents can be tested
- **Tennessee Eastman Process (TEP)**: open Fortran-derived simulator; [IEEE DataPort closed-loop runs](https://ieee-dataport.org/keywords/fault-diagnosis-tennessee-eastman-process-industrial-cyber-physical-systems-large-language) (1676 runs with fault magnitude, noise, valve stiction; tagged for LLM work) [snippet].
- [FaultExplainer, arXiv 2412.14492](https://arxiv.org/abs/2412.14492) (Khan, Nahar, Chen, Dec 2024): PCA detection plus an LLM explaining root causes, tested on TEP [checked].
- LAPSE 2026.0424 ([PDF](https://psecommunity.org/wp-content/plugins/wpor/includes/file/2606/LAPSE-2026.0424-1v1.pdf)): fault-diagnosis tools exposed as MCP tools to an LLM agent; reliable tool calling matters more than model size [snippet].
- Schall 2026, *Autonomous Intelligent Systems* ([DOI 10.1007/s43684-026-00136-1](https://journal.hep.com.cn/ais/EN/10.1007/s43684-026-00136-1)): LLM kept in an observation-only layer, deterministic checks execute; five scenarios, three from TEP [snippet].
- **Our own models** (this repo): the NETL steam-cycle sections and the cumene alkylator heater, solvable on the real DWSIM server, with published reference values.

## 4. How to use these here (proposal, not built)
1. **Deviation generator.** For each solved model, apply guide words to each stream and unit (no / less / more flow, high / low temperature, high / low pressure, reverse flow) through `dwsim_build` / `dwsim_solve`, and store the simulated consequence (T, P, phase, duty change, vapour fraction).
   Example: cumene heater, "less flow" or "more temperature" gives outlet phase and duty; NETL feedwater train, "loss of extraction steam to FWH3" gives the downstream temperature drop.
2. **Reference set.** Pair each deviation with the simulator's consequence as ground truth for what an LLM-generated HAZOP row claims. This directly targets the invalid-scenario rate the Safety Science and NPCW papers report.
3. **P&ID side.** Feed the DEXPI export already in `hysys_bridge` to a ChatP&ID-style graph query to get the node list for deviations.
4. **Dynamic cases.** DWSIM's dynamic tools (`dwsim_dynamics_*`, seen in tools/list) are the route to time-dependent deviations; untested here.
5. **Scoring.** Use the Competence Shadow framework's concern (assistance hiding blind spots) as a checklist: report invalid-scenario rate and missed-deviation rate, not only similarity.

## 5. Limits and next steps
- Steady-state DWSIM models cover only the consequences a steady solve can show; runaway, relief and dynamic hazards need dynamics and a reactor model, which are blocked or untested (column feed stage, reactors).
- Open the [snippet] papers before relying on any number; the two with the most weight are the Safety Science HAZOP study and Liang et al.
- Datasets with expert HAZOP ground truth were not found openly; building a small one from our solved models would be a contribution in itself.
