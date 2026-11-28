# Modelling studies, scenarios and research leads (2026-11-20)

Method: OpenAlex search (public API, 2019 onward, 8 topic queries) and, for the items below, the OpenAlex abstract. **Only titles, venues and abstracts were read; no full text.** Treat every row as a lead to open, not as a verified result. The pasted list of survey tools was checked for existence only (see the end); none was installed or run.
The RSC site (pubs.rsc.org) answered 403 to a plain request, so nothing was fetched from it and no bypass was tried.

## A. LLM and agent work on process simulators (closest to this repo)

| Study | What the abstract says | Use here |
|---|---|---|
| Aspen Assist, Digital Chemical Engineering 2026, doi 10.1016/j.dche.2026.100350 | LLM client, local MCP server and Aspen Python operations for Aspen Plus and Aspen Plus Dynamics; engineer sets the objective and acceptance criteria, changes are logged, evidence is returned | Same architecture as our Aspen backend; compare its acceptance-criteria and change-log design with our `confirm=true` and `assumed_defaults` |
| LLM agent for AVEVA Process Simulation, DCE 2026, doi 10.1016/j.dche.2026.100312 | MCP server drives AVEVA Process Simulation; three case studies from autonomous flowsheet analysis and optimisation to guided use | Task ladder for a copilot evaluation set |
| Text-to-flowsheet, Digital Discovery 2026, doi 10.1039/d6dd00060f | Benchmarks an LLM digitisation pipeline against 50 chemical engineering experts; flowsheet graphs are translated into simulator models | Gives a human baseline; their text descriptions could become our natural-language tasks |
| Sketch2Simulation, arXiv 2603.24629 | Multi-agent system turns process diagrams into executable Aspen HYSYS flowsheets, with multi-level validation | Our PFD generator goes the other way (results to diagram); their validation layers are worth reading |
| ChemE-as-Code, arXiv 2611.07947 | Open-source environment: calculations run outside the LLM, each value records its origin, automated consistency checks; ammonia case for USD 224 of API cost; planted-fault tests show the checks find only what their rules cover | Very close to our "nothing guessed, defaults flagged" rule; read for the provenance scheme and the fault-injection idea |
| AutoChemSchematic AI, arXiv 2505.24584 | Closed-loop generation of PFDs and PIDs with small language models and a knowledge graph | Background for PFD generation |
| PSE-RepairBench (Zenodo 10.5281/zenodo.23657527, listed in your earlier paste with an RSC DOI) | Title: simulator-grounded benchmark for LLM setpoint correction in executable flowsheets | Candidate benchmark for the copilot; confirm it supports DWSIM in a form we can run |
| Learning from flowsheets, Comput. Chem. Eng. 2023, doi 10.1016/j.compchemeng.2023.108162 | Generative transformer for flowsheet autocompletion | Background |

## B. DWSIM validation studies (scenarios with published reference numbers)

| Study | Scenario | Why useful |
|---|---|---|
| Periodica Polytechnica Chem. Eng. 2022, doi 10.3311/ppch.19678 | Plant-wide oil and gas separation plant: flash vessels, valves, splitters, mixers, compressors, heat exchangers, pumps and recycles; DWSIM vs a commercial simulator, generally within 1%, over 90 runs | Best next test: exercises compressor, valve, mixer and splitter, which are on our unverified list, with a published pass/fail |
| IOP Conf. Ser. Earth Environ. Sci. 2020, doi 10.1088/1755-1315/463/1/012057 | Offshore petroleum production, Aspen Plus vs DWSIM | Same family as above |
| ARO 2026, doi 10.14500/aro.12620 and ARO 2023, doi 10.14500/aro.11098 | Combined-cycle gas turbine in DWSIM, design and part load, one case against published HYSYS data | Steam-cycle and gas-turbine numbers to check against our steam and lost-power tools |
| Case Stud. Chem. Environ. Eng. 2026, doi 10.1016/j.cscee.2026.101512 | Corn-stover biorefinery, ethanol organosolv and GVL, NRTL, 100 t/h | Needs columns and liquid-liquid extraction, which the DWSIM MCP server cannot yet configure |

## C. Utilities and refinery modelling leads (for the utilities and refinery tools)

| Topic | Lead |
|---|---|
| Boiler heat recovery | Process-level study of flue-gas latent heat recovery with a condensing heat exchanger in a biomass boiler (2026, University of Cape Town repository); heat recovery system with a steam-turbine CHP unit, Systems and Control Transactions 2025, doi 10.69997/sct.115540. The first bears on the "condensing operation" item still open in `UTILITIES_DESIGN.md` |
| Nitrogen generation | Modelling and simulation of PSA nitrogen for power-to-ammonia, SCT 2026, doi 10.69997/sct.185245; simulation-based optimisation of a cryogenic air separation unit, ACS Omega 2022, doi 10.1021/acsomega.1c06669. Both could replace our assumed second-law efficiency and recovery with published values |
| Steam networks | Industrial power plant under steam demand uncertainty, Energies 2021, doi 10.3390/en14217213; heat recovery system for a petrochemical plant, J. Clean. Prod. 2022, doi 10.1016/j.jclepro.2022.135133 |
| Refinery | Production planning benchmark for refinery-petrochemical complexes, arXiv 2503.22057; CDU and VDU energy optimisation, 2026. These are planning-level, not unit-level, so use for yields and scale checks only |

## D. Suggested next scenarios, in order
1. The oil and gas separation plant (B, first row): verifies compressor, valve, mixer and splitter on the real server, then recycles.
2. The CCGT cases (B): compare `steam_lost_power` and the steam tools against the published steam-cycle numbers.
3. Replace assumed values in `utility_nitrogen_generation` with figures from the two nitrogen papers.
4. Read ChemE-as-Code and Aspen Assist for the provenance and acceptance-criteria patterns, and PSE-RepairBench for an evaluation set.

## E. The survey tools in your paste
Checked with the GitHub API on 2026-11-20 (existence, stars, licence only; code not read): poemswe/co-researcher (139 stars, MIT), SNL-UCSB/literature-survey-skill (117, MIT), Imbad0202/academic-research-skills (about 58k, licence not asserted), keemanxp/slr-prisma (126, licence not asserted), Companion-Inc/feynman (about 10k, MIT), pafloxy/sim-diff (3, MIT), brycewang-stanford/auto-empirical-research-skills (about 5k, licence not asserted). The descriptions in the paste were not checked against the repositories. Installing a skill runs third-party instructions inside this session, so I have not installed any; say which, if any, you want and I will read it first.
