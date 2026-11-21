# DWSIM modelling errors, their causes and fixes, and how the casebook loops use them (2026-11-20)

Purpose: close the build, solve, compare loops without silent errors. Sources are named for every row; what was and was not read is stated first.

## 1. Sources and how much was read
Read in full (text fetched by `fetch_source.py`, official DWSIM tutorial site, no robots restrictions): `reference/troubleshooting`, `intermediate/04-recycle-loops`, `fundamentals/02-degrees-of-freedom`, `fundamentals/03-recycles-and-convergence`, `fundamentals/06-common-mistakes` (all at https://dwsim.org/tutorials/en/).
Read in part: `reference/diagnostics` (the code list: the first 9,500 of 22,096 characters, through the specification codes up to `EFFICIENCY_OUT_OF_RANGE`; the other codes are known from the Common Mistakes page and from the server's own `dwsim_explain_finding`, not from this page).
Fetched, not read: `fundamentals/05-units-and-numbers`.
Seen only as search-result titles and snippets, not opened (treat as leads, not knowledge): SourceForge DWSIM forum threads (recycle block not converging, flash "temperature did not converge", Inside-Out versus Nested-Loops flash for a column), a FOSSEE thread (column "maximum iterations"), HYSYS and Aspen forum threads on cheresources and eng-tips, an AspenTech blog on acid-gas column convergence, a student HYSYS workshop, a CHEMCAD best-practices PDF. One search snippet claims a "Temperature did not converge" PH-flash error went away by reverting from DWSIM 6.4 to 5.5; that is a single anecdote.
The DWSIM documentation was written for the product's own tools; the MCP server section of its troubleshooting page covers only three symptoms.

## 2. Symptom, cause, fix (from the DWSIM pages above)

| Area | Symptom | Cause | Fix | Our code |
|---|---|---|---|---|
| Specification | Solver stops at a unit naming a missing slot; `SPEC_MISSING` | A unit's calculation mode reads a value you did not give (a heater in Outlet Temperature mode needs the outlet temperature; in Heat Added mode, the duty) | Give the value the mode reads, or change the mode | `dwsim_flowsheet_degrees_of_freedom` is the gate before every solve; blocked solves report the open slots |
| Specification | A typed value "changes back" | Over-specified: the box is a result in this mode; DWSIM overwrites it | Set the number on the unit, in the right mode | Product streams are created bare; their specs go on the unit (`_unit_params`) |
| Specification | Heater did nothing (`UNIT_HAD_NO_EFFECT`) | The mode does not read the number that was set (a cooler given an outlet temperature still needs `CalcMode = OutletTemperature`) | Check the mode, then the value | We always send `CalcMode`; the finding is now classified as a backend-mapping fault |
| Specification | Absurd compressor or pump power, `EFFICIENCY_OUT_OF_RANGE` | DWSIM reads efficiencies in percent: 0.75 is three quarters of one percent | Type 75 | Our backend leaves efficiency at the server default (75%); any future efficiency input must be in percent |
| Feed | `FEED_NO_TEMPERATURE`, `FEED_NO_PRESSURE`, `FEED_NO_FLOW`, `FEED_NO_COMPOSITION` | One of the four numbers a feed needs is missing (composition, flow, two of T, P, vapour fraction, enthalpy, entropy) | Enter it; pressure is absolute (1 atm = 101325 Pa, gauge 0 is 1 atm) | Case schema requires a pressure basis; gauge is converted to absolute |
| Feed | Flows differ slightly from what was typed; `FEED_COMPOSITION_NOT_NORMALISED` | Fractions summing to 0.97, or mass typed as mole | Normalise; check the basis | Validator rejects compositions not summing to 1; DWSIM takes mass fractions, so mole bases are converted with stated molar masses |
| Feed | `VAPOR_FRACTION_OUT_OF_RANGE` | 50 typed for 0.5 | Value between 0 and 1 | Not used by our cases |
| Connectivity | "object not connected", unit never calculated; `STREAM_DANGLING`, `UNIT_UNCONNECTED`, `UNIT_NO_FEED`, `UNIT_NO_PRODUCT` | Stream not attached, or attached to the wrong port | Check the unit's connections; every port is named | Validator checks that streams reference real units; the flowsheet check runs before every solve |
| Computed streams | Values typed on a unit's outlet stream vanish | An outlet stream belongs to its unit | Specify on the unit; to fix a mid-flowsheet state use a Recycle block or cut the flowsheet and make it a feed | Same as above |
| Inconsistent spec | Flash fails or converges to nonsense | Two specs no physical state satisfies (temperature below the bubble point with vapour fraction 0.5) | Re-check the pair for physical consistency | Not yet checked by us before a solve |
| Recycle | Solver never starts or takes hundreds of passes; `RECYCLE_NO_ESTIMATE` | No initial values on the tear stream (starts from zero flow); or a loop with no Recycle block | Give an estimate; keep default tolerances while building | Recycles are not yet in our case schema (Phase 3) |
| Recycle | Errors shrink by a few percent per pass | Loop gain near 1 (large recycle share, small purge) | Wegstein acceleration, better estimate | Same |
| Recycle | Errors alternate in sign | Something in the loop responds too strongly (a flash changing phase, a column at its limit) | Switch acceleration off or damp it | Same |
| Recycle | Errors grow every pass | Estimate far from any solution, or the specs have no solution (a purge too small to remove an accumulating inert) | Better estimate; check the specs | Same |
| Recycle | Good starting point | | Solve the open loop first and use its stream as the estimate; ramp the recycle fraction up in steps; reuse the last converged solution; tear a stream with few compounds and no phase change, and tear the stream entering a column | Written into the convergence loop action |
| Column | Not converging | Feed far from saturation; infeasible reflux plus bottoms pair; too few stages | Preheat the feed to its bubble point; try distillate plus bottoms instead; add 5 to 10 stages; raise reflux slightly | Columns are blocked on the server, not used |
| Property package | Density or enthalpy looks wrong | Wrong package or outside its range | Compare pure components with NIST; check T and P are in range | Closure check against CoolProp is planned |
| Property package | Azeotrope missed | PR or Raoult's law on a polar mixture | NRTL or UNIQUAC | Case lists the paper's package and the alternatives |
| Property package | Two packages disagree | Normal; models extrapolate differently | PR for hydrocarbons at moderate pressure, NRTL or UNIQUAC for polar and aqueous, Steam Tables for water | Our cumene case shows this: 6% spread across three packages |
| Plausibility (solve finishes, answer is wrong) | `HEATER_COOLED`, `COOLER_HEATED`, `PRESSURE_WRONG_DIRECTION`, `HX_TEMPERATURE_CROSS`, `HX_HEAT_FLOW_REVERSED`, `TEMPERATURE_BELOW_FREEZING`, `COLUMN_REFLUX_BELOW_MINIMUM`, `MIXER_PRESSURE_MISMATCH` | A sign, spec or basis error; or a real property of the case | Swap the unit or fix the spec; for an exchanger read the T-Q diagram and pinch; for a mixer note which pressure rule DWSIM applied | Recorded as ledger warnings; never "fixed" by changing a published number |
| MCP server | `flowsheet_id` not found | IDs are session-scoped and lost on restart | Save before stopping | Each case run opens its own session |
| MCP server | Solver returns errors but the flowsheet looks right | The `errors` array names the failing object | Read it | Runner returns the server's findings with the object name |
| Edition | "Plus required" | HDS, Reformer, FCC and other refining unit operations, Reverse Osmosis, TEA, LCA and electrolyte NRTL need DWSIM Plus activation | Activate, or avoid | Relevant to any attempt to put refinery conversion units (FCC, hydrotreater) into DWSIM: our refinery tools use surrogate compounds and a heater instead |
| Performance | Very slow, or out of memory | More than 30 components with rigorous packages; slow recycles; many stages; many runs in one process | Lump similar components; simple package for screening; tighten tolerance only for the final solve; restart between large runs | One container per run; it is discarded afterwards |

## 3. Things this changed in our code (2026-11-20)
1. **`ok: true` is not proof of a good solve.** On a deliberately broken flowsheet (a dangling stream, a heater given no duty) the real server's `dwsim_solve_run` returned `ok: true` with `error_count: 0` and put the faults in `findings`. `DwsimBackend.solve()` now runs `dwsim_flowsheet_check` first and refuses on blockers, and treats a blocker finding in the solve response as not solved. All findings are kept in `last_findings`.
2. **Every casebook result carries the findings**, classified by `casebook/diagnose.py` into case errors, backend-mapping faults, plausibility warnings and convergence problems, with the allowed next step; a failed run returns that next step. Warnings reach the ledger as `CODE:severity:object`. An unknown code is flagged as unclassified, never guessed.
3. The live cumene case still solves 9 of 9 with no findings under the stricter gate.

## 4. The loop, closed
Each pass, in this order, stopping at the first failure and logging what changed:
1. Validate the case record (anchors, bases, sums); fix from the source.
2. Build; run the flowsheet check; any blocker means fix the case or the backend mapping, never a number.
3. Degrees of freedom must be zero; open slots are named.
4. Solve; a blocker finding or `ok: false` is a failure whatever else the response says.
5. Read back every spec from the server and compare (`check_solution`).
6. Compare with the published value with the case's tolerance; run every listed property package and report the spread.
7. Closure checks before believing it (the DWSIM checklist): mass balance closes on every mixer, separator and column; energy balance closes; heaters and compressors heat, coolers, valves and expanders cool; pumps and compressors raise pressure; no phase where it should not be; a second package gives a similar answer or the spread is explained. The balance checks in step 7 use `dwsim_explain_result` and are not built yet.

Allowed levers: fix the case record from its source; fix our backend mapping and add a test; for a recycle, the starting-point ladder (estimate, open-loop solve, ramp, acceleration); change the package only as a listed scenario. Not allowed: changing a published number, loosening a tolerance, or dropping a unit until the result matches. Stop after five changes and record the case as unresolved with the diagnosis.

## 5. Not yet verified or built
- Recycle support, partly done (architecture doc section 14): the tutorial loop is a case and passes on the real server, and the server's Recycle properties are known (`AccelerationMethod`, `MaximumIterations`, `SmoothingFactor`; the estimate is the specification on its outlet stream). Still open: the starting-point ladder (the loop converged with no estimate, so it was not needed), acceleration and tolerance in the case schema, and a deliberate non-convergence control (100% recycle).
- Mass and energy closure checks from `dwsim_explain_result`.
- A consistency check before the solve for inconsistent specification pairs.
- The loader error on the 2021 oil and gas file (see section 13 of the architecture doc) is a server problem, outside this table.
