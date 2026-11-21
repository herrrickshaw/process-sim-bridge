# HAZOP deviation worksheet: example-water-exchanger-deviations (case water-counter-current-exchanger-tutorial, hash e05e00087b3b)

> Steady-state simulation only. Causes and safeguards are the study team's input; the tool assigns no severity, likelihood or recommendation. Consequences are changes the flowsheet shows and violations of the declared limits; transients, relief behaviour and dynamics are not evaluated.

> **About this study:** A DEMONSTRATION of the runner on the DWSIM tutorial exchanger. The safe limits below are SYNTHETIC (invented for the demonstration, not plant limits) and the causes, safeguards and sizes are placeholders; nothing here is a real study. The upstream equipment listed for each node is also a placeholder, used only to show the rules-store filter.

**Coverage gap:** node hot-side has no deviation for composition, pressure
**Coverage gap:** node cold-side has no deviation for composition, temperature

| Node | Deviation | Package | Applied | Cause (team) | Consequences (simulation) | Safeguards (team) | Suggestions (rules store, unreviewed) |
|---|---|---|---|---|---|---|---|
| hot-side | MORE flow (HOT_IN) | Steam Tables | mass flow 3600 to 5400 kg/h | placeholder: upstream control valve fails open | no new violation or finding [HOT_OUT T 86.13 to 97.64; COLD_OUT T 47.44 to 49.05; COLD_OUT vapor_fraction 0 to 0] | placeholder | causes: valve fully open; increased pump speed; increased pressure difference / safeguard types: process alarms; standard operating procedures |
| hot-side | NONE flow (HOT_IN) | Steam Tables | mass flow 3600 to 0.36 kg/h | placeholder: upstream pump trips | no_solution: no steady-state solution at the deviated condition: X: failed to calculate the Number of Transfer Units (NTU) with the current input and specs; findings NOT_CONVERGED, SOLVER_EXCEPTION | placeholder | causes: valve closed; pump failure; incorrect pressure difference; major leakage / safeguard types: process alarms; standard operating procedures |
| hot-side | REVERSE flow (HOT_IN) | Steam Tables | - | placeholder | not_evaluable: reverse flow cannot be represented in a steady-state flowsheet; assess it by another method |  | causes: pump trip; incorrect differential pressure; check valve passing / safeguard types: process alarms; standard operating procedures |
| hot-side | MORE temperature (HOT_IN) | Steam Tables | temperature 126.9 to 141.9 C | placeholder: heater overshoot | limit_violation: T_C 132.8 against {'max': 100.0} [HOT_OUT T 86.13 to 132.8; COLD_OUT T 47.44 to 55.53; COLD_OUT vapor_fraction 0 to 0] |  | causes: heater control failure; runaway reaction / safeguard types: process alarms; standard operating procedures |
| cold-side | LESS flow (COLD_IN) | Steam Tables | mass flow 7200 to 1800 kg/h | placeholder: strainer blockage | limit_violation: T_C 89.03 against {'max': 60.0} [HOT_OUT T 86.13 to 96.11; COLD_OUT T 47.44 to 89.03; COLD_OUT vapor_fraction 0 to 0] | placeholder | causes: pump cavitation; fouling; partial blockage / safeguard types: process alarms; standard operating procedures |
| cold-side | NONE flow (COLD_IN) | Steam Tables | mass flow 7200 to 0.72 kg/h | placeholder: pump trip | limit_violation: T_C 126.7 against {'max': 100.0}; limit_violation: T_C 126.9 against {'max': 60.0} [HOT_OUT T 86.13 to 126.7; COLD_OUT T 47.44 to 126.9; COLD_OUT vapor_fraction 0 to 1] |  | causes: valve closed; pump failure; incorrect pressure difference; major leakage / safeguard types: process alarms; standard operating procedures |
| cold-side | LESS pressure (COLD_IN) | Steam Tables | pressure 101.3 to 81.33 kPa | placeholder | limit_violation: P_kPa 76.33 against {'min': 90.0} [HOT_OUT T 86.13 to 86.13; COLD_OUT T 47.44 to 47.44; COLD_OUT vapor_fraction 0 to 0] |  | causes: pump or compressor failure / safeguard types: process alarms; standard operating procedures; pressure safety valves |

**Sources of the suggestions** (candidates for the team, none reviewed):
- HAZOP Tutorial, SafeChE, University of Michigan (Table 2, Typical Causes of Deviations in Process Parameters; steps 3 to 6) (https://safeche.engin.umich.edu/tutorials/hazop-tutorial); read in full from a Wayback copy dated 2025-08-11 (the live page answered a bot challenge, which was not bypassed); licence: none seen on the page; facts only, causes restated as short generic phrases, no text copied beyond names of failure modes
- Lecture 13, Hazard and Operability Studies (HAZOP), Dr. Raghuram Chetty, IIT Madras, NPTEL course 103106071 (Chemical Plant Safety and Risk Assessment) (https://archive.nptel.ac.in/content/storage2/courses/103106071/lec13.pdf); fetched once and read in full (text layer, 13,203 characters); licence: none seen on the file; facts only, the worked examples are summarised, not copied
- Method note: Consequences are written assuming the existing safeguards are not working.
- Method note: Safeguards are protections in place; recommendations are protections to be added.
- Method note: Not considered in a HAZOP: simultaneous unrelated incidents, simultaneous failure of more than one independent protection, natural calamity, sabotage.
- Method note: HAZOP does not identify all causes, takes little account of probabilities, is poor where multiple-combination events matter, and tends to ignore operator intervention.
- Method note: HAZOP identifies hazards; it is not a means of solving problems.
- Mapping: causes the source lists for 'other composition than usual' are offered for both AS_WELL_AS and PART_OF (this tool's mapping)

7 deviations: 4 with a new limit violation, 1 without a steady-state solution, 1 not evaluable.
