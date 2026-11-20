# Unit operations: what Aspen documents, what the DWSIM server offers, what we have verified (2026-11-20)

Question asked: check Aspen whitepapers and publications for more units. Answer in short: AspenTech publishes no whitepaper that lists unit models; what it does publish is certification study guides (objectives, not manuals), product pages for the refinery reactors, and the Unit Operation Models reference manual (not found openly). The model names below therefore come from three tiers of source, marked in every row.

## 1. Sources and what was read
- **Official, read:** two AspenTech certification study guides (Aspen Plus with Distillation Modeling, and the Expert guide, 2019) fetched from aspentech.com (robots.txt allows `/-/media/`; its 10-second crawl delay was observed) and the "Refinery Reactor Models in Aspen HYSYS" product page. The guides list competency objectives, so they name only some blocks: Mixer, SSplit, Flash2, Flash3, Decanter, a component-splitter block, Heater (including dew-point outlet and heat streams), HeatX (and its link to Aspen Exchanger Design and Rating), the shortcut columns, RadFrac (43 mentions: on-stage versus above-stage, non-equilibrium stages, rate-based), the reactor classes (balance-based, RGibbs, RCSTR), convergence (tear streams, Newton), sensitivity analysis, and equation-oriented models. The product page names the HYSYS refinery reactor suite: FCC, hydrocracking, hydrotreating, naphtha reforming, isomerisation, alkylation, delayed coking, visbreaking (the search snippet adds CatCracker and "lump" kinetics; the page text read lists no model parameters).
- **Secondary, search snippets only (not opened):** course notes and slides on Scribd and university sites, an Aspen Plus input-language guide on a university server, a Virginia Tech dissertation on an FCC plant in HYSYS, a book index on FCC lump models. They supply the names Pump, Compr, MCompr, Valve, Pipe, Pipeline, FSplit, Sep, RStoic, RYield, REquil, RPlug, RBatch, DSTWU, Distl, Extract, MultiFrac and PetroFrac. Treat the names as leads; no behaviour was taken from them.
- **Not found openly:** the Aspen Plus Unit Operation Models reference manual and any open-access 2024 to 2025 paper built around a block list. Searching a journal database (MDPI Processes, ACS Omega, Chem. Eng. Res. Des.) with open-access filters is the next step if a published Aspen case is wanted.
- **The server side:** the 44 unit types the DWSIM MCP server lists (queried live), and the DWSIM tutorial index (titles only; those pages were not read except Recycle Loops and the fundamentals pages).

## 2. Coverage table
Status key: **verified** = built through our casebook or tool path and run on the real server with a result checked; **server has it** = the DWSIM server offers the type but we have not driven it; **blocked** = known obstacle; **none** = no DWSIM analogue found in the server's list. The Aspen-to-DWSIM pairing is my engineering judgement (analogue, not a proven equivalent).

| Function | Aspen Plus block (tier) | HYSYS operation | DWSIM server type | Our IR type | Status | Reference case available |
|---|---|---|---|---|---|---|
| Mixer | Mixer (official) | Mixer | Mixer | mixer | **verified** (recycle loop; mixer tutorial with an independent CoolProp oracle, 9 runs) | done |
| Splitter | FSplit, SSplit (official: SSplit) | Tee | Splitter | splitter | verified: split ratio (recycle loop), outlet mass flow (earlier) | tutorial recycle loop (done) |
| Component separator | Sep (secondary) | Component Splitter | ComponentSeparator | none | server has it | none yet |
| Flash, two phase | Flash2 (official) | Separator | Vessel | separator | **verified** against the flash drum tutorial (NRTL matches its values; PR and SRK differ as expected for a polar mixture); port 0 = vapour, port 1 = liquid | done |
| Flash, three phase | Flash3, Decanter (official) | 3-Phase Separator | Vessel (phase settings unknown) | none | not driven | none |
| Heater, cooler | Heater (official) | Heater, Cooler | Heater, Cooler | heater, cooler | **verified** with an independent CoolProp oracle through a phase change: Steam Tables within 0.07%, cubic EOS 4 to 15% off for water (cumene heater and recycle loop earlier) | done |
| Heat exchanger | HeatX (official), MHeatX | Heat Exchanger | HeatExchanger | exchanger (in schema, not mapped) | server has it; not driven | DWSIM Heat Exchanger Design (not read) |
| Pump | Pump (secondary) | Pump | Pump | pump | verified parameter mapping; no published duty case yet | cumene pumps (needs table matching) |
| Compressor | Compr, MCompr (secondary) | Compressor | Compressor | compressor | parameter mapping verified; no published case | oil and gas plant (blocked, see architecture doc section 13), CCGT |
| Expander, turbine | Compr in expander mode (secondary) | Expander | Expander | none | server has it | CCGT cases |
| Valve | Valve (secondary) | Valve | Valve | valve | parameter mapping verified (isenthalpic check); no published case | oil and gas plant |
| Pipe | Pipe, Pipeline (secondary) | Pipe Segment | Pipe | none | server has it | none |
| Recycle (tear stream) | convergence options, tear streams (official) | Recycle | Recycle | recycle | **verified** (tutorial loop, 8 runs within 0.04%) | done |
| Design spec, adjust | Design Spec, Calculator, Sensitivity (official) | Adjust, Set, Spec | Adjust, Spec | none | server has the types; no use of them | DWSIM tutorials with an adjust (not read) |
| Shortcut column | DSTWU, Distl (official: "shortcut methods"; names secondary) | Shortcut Column | ShortcutColumn | column (not mapped) | server has it; the server could not assign a feed stage for rigorous columns | DWSIM Distillation Column tutorial (not read) |
| Rigorous column | RadFrac (official, 43 mentions), MultiFrac, PetroFrac (secondary) | Distillation Column | DistillationColumn, AbsorptionColumn | column | **blocked** (feed-stage assignment) | Benzene/Toluene, Ethanol Plant tutorials (not read) |
| Stoichiometric reactor | RStoic (secondary) | Conversion Reactor | ConversionReactor | reactor (not mapped) | server has it plus reaction-set tools (`dwsim_reaction_add_conversion`, `reactionset_create`) | DWSIM Reaction Systems (not read) |
| Equilibrium reactor | REquil (secondary), RGibbs (official) | Equilibrium, Gibbs Reactor | EquilibriumReactor, GibbsReactor | reactor | server has it (`reaction_add_equilibrium`) | Ammonia, Methanol Synthesis tutorials (not read) |
| Kinetic reactors | RCSTR (official), RPlug (secondary) | CSTR, PFR | CSTR, PFR | reactor | server has it; kinetics tooling not seen | none yet |
| Refinery conversion | none in Aspen Plus; HYSYS refinery reactor suite: FCC, hydrocracker, hydrotreater, reformer, isomeriser, alkylation, coker, visbreaker (official page) | Refinery reactors | none in the core server; "Refining unit operations (HDS, Reformer, FCC)" need DWSIM Plus (DWSIM troubleshooting page) | none | **blocked** | our `refinery_run` yield balance is a separate screening model, not these units |
| Batch reactor | RBatch (secondary) | Batch reactor | BioReactor and others, no direct analogue seen | none | none | none |
| Storage | none | Tank | Tank | none | server has it | none |
| Filters, solids | Crystallizer, Filter, Cyclone and others (secondary, not verified) | Solids operations | Filter, SolidsSeparator, Crystallizer, Centrifuge | none | server has them | none |
| Dynamics | Aspen Plus Dynamics (official: Aspen Assist paper) | HYSYS Dynamics | `dwsim_dynamics_*` tools (13) | none | not driven | DWSIM dynamics tutorials (not read) |

## 3. What the gap analysis says
1. The units not yet driven but present on the server, and with free reference cases in DWSIM's own tutorials (each lists expected results): **HeatExchanger, Expander, Vessel as a flash with published numbers, ShortcutColumn, ConversionReactor, EquilibriumReactor, ComponentSeparator, Adjust and Spec, Pipe, Tank.** That is ten more units on the same footing as the recycle case.
2. Reference tutorials worth reading next (titles known from the site index, content not read): Heat Exchanger Design, Simple Flash Drum, Mixer Basics, Reaction Systems, Distillation Column (shortcut), Refrigeration Cycle (compressor, valve, two exchangers in a loop), Natural Gas Processing, Ammonia Synthesis and Methanol Synthesis (reactor plus recycle plus purge, the case the recycle page itself points to), Benzene/Toluene Separation.
3. Genuinely blocked: rigorous columns and refinery conversion units on the open server. For refining, the Aspen route (HYSYS refinery reactor suite) is the commercial one and is outside what this repo can run; the screening model stays the stand-in.
4. The Aspen backend side: our Aspen backend works over a tree protocol and has never run against a real Aspen Plus, so no Aspen unit is verified. The block names in section 2 (Mixer, FSplit, SSplit, Sep, Flash2, Flash3, Decanter, Heater, HeatX, Pump, Compr, Valve, DSTWU, RadFrac, RStoic, REquil, RGibbs, RCSTR, RPlug) are the ones to implement in `hysys_bridge/aspen/` when a licensed copy is available; the official guides confirm the subset marked official.
5. Aspen's certification objectives that matter for the loops: convergence (tear streams, Newton), sensitivity analysis, design specs, heat streams on a heater, and the dew-point outlet specification. Each has a DWSIM counterpart in section 2 and a pending case.

## 4. Suggested order for the next cases (each is one slice with its own reference)
1. ~~Simple flash drum and mixer~~ done (architecture doc section 15).
2. ~~Heater and cooler duties~~ done (architecture doc section 16); next heat exchanger design.
3. Refrigeration cycle (compressor, valve, evaporator, condenser): first loop with a compressor and valve and a published coefficient of performance.
4. Conversion reactor, then ammonia or methanol synthesis (reactor plus recycle plus purge).
5. Shortcut distillation, then the benzene/toluene column if feed-stage assignment is solved.
Read each tutorial page in full before building its case, as was done for the recycle loop.
