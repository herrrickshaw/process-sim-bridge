# HAZOP combined with process simulation: literature found (2026-11-21)

Method: web searches only. The papers below were located from search results and abstracts; none was read in full, and access status (open or paywalled) is stated only where a search result showed it. No simulation or tool in this repo has been built from them yet.

## Simulation-based HAZOP (the closest to this repo)
| Paper | What it does | Link |
|---|---|---|
| Janosovsky et al., "Automated Model-based HAZOP Study in Process Hazard Analysis", Chemical Engineering Transactions 48 (2016) | Custom tool drives Aspen HYSYS: generates deviations, simulates, reads results back | https://www.aidic.it/cet/16/48/085.pdf |
| "Development of a Software Tool for Hazard Identification Based on Process Simulation", CET 77 (2019) | Quantitative guide words NONE, MORE, LESS, REVERSE; the deviation must be sized; parametric sensitivity and steady-state multiplicity checks; tested on an ammonia synthesis plant and a propylene glycol process | https://www.aidic.it/cet/19/77/059.pdf |
| "Software approach to simulation-based hazard identification of complex industrial processes", Computers & Chemical Engineering (2018) | HAZOP-style report of deviations, causes, consequences from semi-automatic evaluation of simulation results | https://www.sciencedirect.com/science/article/abs/pii/S0098135418305179 |
| "The role of a commercial process simulator in computer aided HAZOP approach", Process Safety and Environmental Protection (2017) | Role of a commercial simulator (title and abstract only) | https://www.sciencedirect.com/science/article/abs/pii/S095758201730023X |
| Janosovsky and colleagues, bottlenecks of computer-aided HAZOP, CET 67 (2018) | Practical obstacles when HAZOP deviations are simulation inputs | https://www.aidic.it/cet/18/67/039.pdf |
| Pitt, IChemE Symposium Series 139 (1995) | Steady-state PRO/II runs on a naphtha stabiliser before and after each guide-word deviation; notes a steady-state simulator cannot show start-up or shutdown | https://www.icheme.org/media/25360/major-hazards-onshore-and-offshore-ii-icheme-symposium-series-139-1995-36-pitt.pdf |
| "A simulation based engineering method to support HAZOP studies" (book chapter) | Systematic failure scenarios from equipment deviations, evaluated with dynamic simulation | https://www.sciencedirect.com/science/chapter/bookseries/abs/pii/B9780444595065500857 |

## Dynamic simulation with HAZOP (found earlier)
Berdouzi et al. on HAL (https://hal-ineris.archives-ouvertes.fr/ineris-01863859/file/2017-267_post-print.pdf), Danko et al. CET 67 (https://www.aidic.it/cet/18/67/048.pdf), Tian, Du and Mu (Wiley).

## Ontology, knowledge-graph and review literature
- "Automation for HAZOP study: A state-of-the-art review and future research directions" (https://www.researchgate.net/publication/384450916_Automation_for_HAZOP_study_A_state-of-the-art_review_and_future_research_directions), the best survey lead.
- Single et al., ontology-based HAZOP worksheet generation: https://kluedo.ub.rptu.de/frontdoor/index/index/docId/6741
- Li and Zhao, HAZOP knowledge graph, ESCAPE 34 (2024): https://www.aidic.it/escape34-pse24/programma/335Li.docx
- Industrial safety knowledge graph from HAZOP reports (arXiv): https://arxiv.org/pdf/2111.13854
- Ontology-based generation of training scenarios from HAZOP: https://aiche.org/conferences/aiche-annual-meeting/2018/proceeding/paper/182t-ontology-based-automated-generation-training-scenarios-development-process-safety-rule-engine
- 2026 preprint review of digital twins and AI extending HAZOP (not peer reviewed): https://www.preprints.org/manuscript/202606.1902/v1

## Gaps and use for this repo
- No result mentioned DWSIM. Every simulator-coupled tool found uses HYSYS, Aspen or PRO/II, so a DWSIM route through the MCP server would be new.
- The 2019 CET method maps onto the casebook: a guide word plus a parameter is a scenario override (for example MORE flow = a feed mass-flow override), and the "deviation size" the paper insists on is the override value. What the casebook cannot do yet is judge a consequence (no safety limits in the case schema) or run dynamics.
- The repo has `hysys_bridge/safety_link.py` (relief-valve sizing from a solved stream, API 520); it is not a HAZOP tool. Connecting deviation scenarios to a consequence check is the open step.
