# Survey: documented process simulations, thermodynamic models and accessible tools (2026-11-20)

Evidence tags: **[snippet]** = from a search-result snippet, not opened; **[ran]** = reproduced here with our tools; **[API]** = checked through GitHub/arXiv APIs.
No published validation study below was reproduced except where marked [ran].

## 1. Documented simulations and validations (what exists)
| Work | What it documents | Level |
|---|---|---|
| Andreasen, "Evaluation of an open-source chemical process simulator using a plant wide oil and gas separation plant flowsheet model" ([repo andr1976/dwsim-paper](https://gh.r-mj.com/andr1976/dwsim-paper)) | Same oil-and-gas separation plant in DWSIM and Aspen HYSYS; base-case benchmark and a 100-case parametric study with scripts | [snippet] |
| Nayak et al. | DWSIM vs Aspen Plus vs OpenModelica; DWSIM and Aspen Plus compared well | [snippet] |
| [Evaluation of the open source process simulator DWSIM for bioprocess simulation (Periodica Polytechnica, 2024)](https://pp.bme.hu/ch/article/download/23166/22383) | Bioethanol production in DWSIM | [snippet] |
| Gas compression and LNG comparisons (DWSIM vs Aspen Plus), cited by the [BME paper](https://pp.bme.hu/ch/article/download/19678/9410) | Agree "well", with detail missing for a thorough assessment | [snippet] |
| Own work this session: NETL Case B11A steam cycle, cumene alkylator heater | Pump + four feedwater heaters (enthalpies within 0.26 Btu/lb of CoolProp), heater duty within 3.5% of the published HYSYS duty | [ran] |

Gap stated by the literature itself: validation and testing of open-source simulators is thin; no systematic multi-simulator, multi-package benchmark was found.

## 2. Thermodynamic models: guidance found
- Model choice drives convergence and correctness; EoS (PR, SRK) for hydrocarbons and gases, activity-coefficient models (NRTL, UNIQUAC, Wilson) for non-ideal liquids; Wilson cannot do LLE ([Northwestern property-package notes](https://processdesign.mccormick.northwestern.edu/index.php/Property_package)) [snippet].
- Book-length treatment of selecting models for process simulation ([IFP Énergies nouvelles e-book](https://books.ifpenergiesnouvelles.fr/ebooks/thermodynamics/table_of_contents.html)) [snippet].
- NeqSim model list ([docs](https://equinor.github.io/neqsim/thermo/thermodynamic_models)) [snippet].
- No quantitative PC-SAFT vs cubic vs GE-model accuracy survey turned up in two searches.

## 3. Accessible simulation tools
Open or free: DWSIM (GPL-3.0, with an MCP server, used here), COCO (free, not fully open), NeqSim (Apache-2.0), IDAES/Pyomo, tespy (MIT), CoolProp (MIT), CalebBell `thermo`/`chemicals`/`fluids`/`ht` (MIT), feos, thermopack, Clapeyron.jl, Cantera, Reaktoro; licences and dates from the GitHub API are in `docs/RESEARCH_TOOLS_AND_PAPERS.md` [API]. A [Wikipedia list of chemical process simulators](https://wikiwand.com/en/List_of_chemical_process_simulators) gives the commercial and academic ones [snippet]. Commercial (Aspen Plus/HYSYS) need a licence; the Aspen backend here is untested for that reason.
User reviews of DWSIM report crashes and gaps in interaction-parameter databases [snippet]; we saw the server's container die once on a long benchmark (fixed by closing flowsheets).

## 4. Data for testing thermodynamic models
- NIST/TRC SRD 93 VLE database: commercial (archived listing about $5,090) [snippet]; DECHEMA VLE series: printed, paid; Landolt-Börnstein: paid.
- Free: [NIST TRC ThermoML records](https://trc.nist.gov/ThermoML/10.1021/je700710d.html) (per-paper experimental VLE; whether raw files download freely not verified) and the [UT ThermoDex VLE collection record](https://thermodex.lib.utexas.edu/record/vapor-liquid-equilibrium-data-collection/) [snippet].
- The CC-BY Rodare dataset of binary mixtures is simulator-generated, not experimental, so unsuitable as a benchmark [snippet].
- Used here instead: CoolProp's HEOS mixture model (a fitted reference calculation) and the textbook ethanol-water azeotrope (78.15 C at 89.4 mol%).

## 5. Modelled with our tools [ran]
Script: `examples/vle_benchmark.py` (Heater as a T-P flash, through `DwsimBackend` on the real DWSIM server; CoolProp 8.0.0 for reference).

**A. Propane / n-butane, z = 0.5, 500 kPa, flashed at 26.38 C** (CoolProp bubble 19.58 C, dew 33.18 C; CoolProp VF 0.481, x_C3 0.362, y_C3 0.649)
| DWSIM package | VF | x_C3 | y_C3 | error vs CoolProp (VF, x, y) |
|---|---|---|---|---|
| Peng-Robinson | 0.504 | 0.354 | 0.643 | +0.024, -0.008, -0.005 |
| SRK | 0.503 | 0.354 | 0.644 | +0.022, -0.008, -0.005 |
| Raoult's law | 0.515 | 0.331 | 0.659 | +0.034, -0.031, +0.010 |

**B. Ethanol / water, 101.325 kPa, bubble temperature in C** (literature: water 100.0, ethanol 78.3 to 78.4, azeotrope 78.15 at x = 0.894)
| DWSIM package | water | x = 0.894 | ethanol |
|---|---|---|---|
| NRTL | 99.99 | 78.39 | 78.66 |
| UNIQUAC | 99.99 | 78.33 | 78.66 |
| Wilson | 99.99 | 78.31 | 78.66 |
| Peng-Robinson | 99.99 | 75.93 | 78.66 |
| Raoult's law | 99.99 | 80.21 | 78.66 |

Reading: for the hydrocarbon pair, PR and SRK are close to CoolProp, Raoult's law is clearly worse in liquid composition. For ethanol-water the activity-coefficient models land within about 0.25 C of the azeotrope; PR without ethanol-water interaction parameters is 2.2 C low and the ideal-solution model 2.1 C high, as expected. All packages give ethanol at 78.66 C, 0.3 C above the usual 78.3 to 78.4: that is DWSIM's pure-component vapour-pressure data, not the mixture model. Caveats: CoolProp is a model, not raw measurements; the literature values are textbook figures; one pressure and composition each; bubble point found by bisection to 0.02 C.

## 5b. Andreasen oil-and-gas plant, 100-case re-run [ran]
`examples/andreasen_rerun.py` loads the paper's own `optimisation.dwxmz` (42 unit operations, 20 compounds with pseudo-components, recycles) into the DWSIM 10.2.16 MCP server and applies
the paper's 100-point Latin-hypercube plan (10 set-points) through our client; `examples/andreasen_stats.py` compares with the paper's published result files
(MIT repo andr1976/dwsim-paper; its DWSIM 7 and Aspen HYSYS results). Raw output: `examples/results/andreasen_rerun_dwsim_10.2.16.json`.
All 100 cases solved. In the first long run cases 62 and 63 failed at once and solved when retried after a fresh load of the flowsheet (stale solver state, not infeasibility); the final run, which reloads the flowsheet automatically on a failed solve as the paper's own script does, solved all 100 in one pass.

| Output | vs paper's HYSYS (100 cases) | vs paper's DWSIM 7 (88 usable cases) | for scale: paper's DWSIM 7 vs HYSYS |
|---|---|---|---|
| Crude flow, kmol/h | MAE 0.035%, max 0.10% | MAE 0.087%, max 0.40% | MAE 0.112%, max 0.48% |
| Compressor + pump power, kW | MAE 0.104%, max 0.49% | MAE 0.277%, max 2.11% | MAE 0.352%, max 2.40% |
| RVP (Reid vapour pressure proxy), psi | MAE 0.117%, max 1.67% | MAE 0.268%, max 1.48% | MAE 0.366%, max 1.81% |

Correlation with HYSYS is 0.9999 on all three outputs.

**Vapour ratio** (vapour-phase over liquid-phase volumetric flow of the product stream, the paper's fourth output): the paper's script evaluates it before each solve, so its row i is the state left by case i-1 (row 0 is the base file). Our paper-faithful value matches the paper's DWSIM 7 file with MAE 0.0032% (max 0.039%, 88 rows); read after the solve of case i-1 against row i the MAE is 0.0031%, against row i with no lag 0.037%, which confirms the one-case lag. The ratio is recovered from phase densities (V_total = m/rho_mix = m_v/rho_v + m_l/rho_l) because the MCP results give no phase volumetric flows; for case 0 that gives 4.007735 against the paper's 4.007733. Its correlation (r = 0.987) is lower than the other outputs only because the ratio barely varies (3.993 to 4.009 across all cases). 12 rows of the paper's DWSIM 7 file are excluded from the DWSIM 7 columns: 9 hold -9999 (cases that did not solve) and 3 (34, 50, 63) are
identical to the row before them in all three outputs, which cannot happen by chance and shows a stale solver state in the paper's run (case 63 matched case 62 exactly; ours matches HYSYS there,
12,388 vs 12,384 kW). Our earlier apparent 1.4% miss on case 34 was that stale paper row. Read with care: only agreement between two simulators is shown, not accuracy against plant data; the reference results come from DWSIM 7 and a particular HYSYS version, ours from DWSIM 10.2.16, and the compared numbers are the paper's
published CSVs, not a fresh HYSYS run. Takeaway: through our MCP client, the current DWSIM reproduces the paper's HYSYS results on this plant-wide flowsheet to about 0.1% and agrees with the paper's own DWSIM 7 run
about as closely as that run agreed with HYSYS.

## 6. Next steps
1. ~~Re-run Andreasen's plant~~ done (section 5b); next: repeat with a fresh HYSYS or NeqSim run as an independent third simulator.
2. Pull ThermoML raw ethanol-water and hydrocarbon VLE sets and score each package by deviation, replacing CoolProp as reference.
3. Add CalebBell `thermo` as a second independent reference, and NeqSim as a second simulator.
4. Extend the benchmark to LLE (needs a three-phase check) and to PC-SAFT/CPA systems (DWSIM lists PC-SAFT).
