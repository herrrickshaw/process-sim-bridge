# HAZOP deviation worksheet: example-water-exchanger-deviations (case water-counter-current-exchanger-tutorial, hash e05e00087b3b)

> Steady-state simulation only. Causes and safeguards are the study team's input; the tool assigns no severity, likelihood or recommendation. Consequences are changes the flowsheet shows and violations of the declared limits; transients, relief behaviour and dynamics are not evaluated.

> **About this study:** A DEMONSTRATION of the runner on the DWSIM tutorial exchanger. The safe limits below are SYNTHETIC (invented for the demonstration, not plant limits) and the causes, safeguards and sizes are placeholders; nothing here is a real study.

**Coverage gap:** node hot-side has no deviation for composition, pressure
**Coverage gap:** node cold-side has no deviation for composition, temperature

| Node | Deviation | Package | Applied | Cause (team) | Consequences (simulation) | Safeguards (team) |
|---|---|---|---|---|---|---|
| hot-side | MORE flow (HOT_IN) | Steam Tables | mass flow 3600 to 5400 kg/h | placeholder: upstream control valve fails open | no new violation or finding [HOT_OUT T 86.13 to 97.64; COLD_OUT T 47.44 to 49.05; COLD_OUT vapor_fraction 0 to 0] | placeholder |
| hot-side | NONE flow (HOT_IN) | Steam Tables | mass flow 3600 to 0.36 kg/h | placeholder: upstream pump trips | no_solution: no steady-state solution at the deviated condition: X: failed to calculate the Number of Transfer Units (NTU) with the current input and specs; findings NOT_CONVERGED, SOLVER_EXCEPTION | placeholder |
| hot-side | REVERSE flow (HOT_IN) | Steam Tables | - | placeholder | not_evaluable: reverse flow cannot be represented in a steady-state flowsheet; assess it by another method |  |
| hot-side | MORE temperature (HOT_IN) | Steam Tables | temperature 126.9 to 141.9 C | placeholder: heater overshoot | limit_violation: T_C 132.8 against {'max': 100.0} [HOT_OUT T 86.13 to 132.8; COLD_OUT T 47.44 to 55.53; COLD_OUT vapor_fraction 0 to 0] |  |
| cold-side | LESS flow (COLD_IN) | Steam Tables | mass flow 7200 to 1800 kg/h | placeholder: strainer blockage | limit_violation: T_C 89.03 against {'max': 60.0} [HOT_OUT T 86.13 to 96.11; COLD_OUT T 47.44 to 89.03; COLD_OUT vapor_fraction 0 to 0] | placeholder |
| cold-side | NONE flow (COLD_IN) | Steam Tables | mass flow 7200 to 0.72 kg/h | placeholder: pump trip | limit_violation: T_C 126.7 against {'max': 100.0}; limit_violation: T_C 126.9 against {'max': 60.0} [HOT_OUT T 86.13 to 126.7; COLD_OUT T 47.44 to 126.9; COLD_OUT vapor_fraction 0 to 1] |  |
| cold-side | LESS pressure (COLD_IN) | Steam Tables | pressure 101.3 to 81.33 kPa | placeholder | limit_violation: P_kPa 76.33 against {'min': 90.0} [HOT_OUT T 86.13 to 86.13; COLD_OUT T 47.44 to 47.44; COLD_OUT vapor_fraction 0 to 0] |  |

7 deviations: 4 with a new limit violation, 1 without a steady-state solution, 1 not evaluable.
