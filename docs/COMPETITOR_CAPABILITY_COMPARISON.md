# Capability comparison: Drishya AI, myosh and this repository (2026-11-21)

Asked: check the service offerings of companies like Drishya AI and others ("myosh and prou") against the overall capabilities of this tool.

## What was read, and what was not
- **Drishya AI** (https://www.drishya.ai): the home page and ten product and solution pages (Artisan, Brains, Junior, the Computable Contextual Graph, HYSYS flowsheet automation, P&ID and isometric digitization, smart data sheet analysis, alarm intelligence, HAZOP-driven root cause analysis, process optimization), one request each, 2026-11-21. Everything below about Drishya is **what the vendor's pages say**; the speed-up and accuracy figures (for example "90% faster", "3 to 4 days not 3 to 6 weeks", "100% data accuracy", "failures predicted 15+ hours early") are marketing claims with no method or evidence on the pages, and none was tested.
- **myosh** (https://www.myosh.com): the home page, the modules page, the AI page, the Digital Bow-Tie page, the critical control management page and the chemical industry page. Same caveat: vendor statements.
- **ProU Technology** (https://www.prou.com.au, Australia; identified from the address you gave): the home page only, one request. It is script-rendered (a plain fetch returned 56 characters; the text came from a rendered fetch) and exposed no links, so **no product subpage was read** and the description below is the home page's own summary, with no evidence behind its claims.
- **"And others"**: a search for AI-assisted HAZOP and process-safety platforms returned names I only saw as titles and snippets, not read: Vysus HAZOP Assistant, ABB Ability SafetyInsight, Symphony AI IRIS Foundry (P&ID digitization), Wolters Kluwer Enablon, Primatech PHAWorks, Cenosco IMS SIS, Cority, Evotix and IOMOSAIC PSMPro. They are leads for a next pass, not part of the table below.
- **This repository**: described from its own tool list (46 MCP tools), README and docs, and the test results recorded there. "Verified" below means a recorded test or a live run against a real server, not a claim of fitness for plant use.

## The vendors are different kinds of product
- **Drishya AI** is an engineering-data platform for EPC and operating companies: it turns drawings and data sheets into a connected model (a "contextual graph") and builds deliverables, simulations, answers and operations insight on it.
- **myosh** is an EHS (health, safety, environment, quality) management system: records, workflows, registers, audits, bow-ties and analytics for people-and-compliance management, with no process simulation.
- **ProU Technology** sells ProHaz AI, a safety-study suite: AI-assisted HAZOP, SIL and LOPA, and bow-tie worksheets, with P&ID extraction and a "chat with P&ID" assistant, a rules engine, multi-user governance and offline desktop use. Of the three vendors it is the closest to this repository's diagram and HAZOP-with-simulation direction, but it appears to be a documentation and workflow product for safety studies, not a simulator link (nothing on the page mentions process simulation).
- **This repository** is open tooling that links diagrams, heat and mass balances and published reference cases to process simulators (HYSYS, DWSIM, Aspen) with an evidence trail. It has no user interface, no multi-user data store and no live plant connection.
So the overlap is partial, and the fair question is which capability areas each one covers.

### ProU (home page statements) against this repository
| ProU capability (as stated) | This repository |
|---|---|
| HAZOP, SIL/LOPA and bow-tie study automation, worksheet and report generation | **None.** No worksheet, SIL or LOPA tool; the only HAZOP material is a literature survey and the idea that a guide word plus parameter becomes a casebook scenario |
| P&ID extraction by vision AI plus LLM, tag extraction, "chat with P&ID" | **Partial.** `extract_pid` (LLM topology draft, flagged for sign-off, reconcile rules, scoring) and an MCP interface a client can query; no tag-level extraction, no editing of the drawing |
| Smart analytics: safety KPIs, anomaly detection | **None** |
| Multi-user workflows, approvals, audit trail, role-based access | **Partial:** run ledger and sign-off gates only; no users or roles |
| Knowledge and rules engine (reusable deviations, safeguards, risk logic) | **Partial:** the guardrail registry (OSHA rules, advisory rules) and the findings classifier hold rules, but not HAZOP deviations or safeguards |
| Offline and edge desktop access | **Have in a sense:** it runs locally, with no cloud dependency except the optional LLM call in `extract_pid` |
| Simulation | Not mentioned on the page; this repository's distinguishing strength (verified simulator links and reference cases) | 

## Capability matrix
Status for this repository: **have** (built and tested), **partial**, **none**. Vendor columns are what the pages state.

| Capability area | Drishya AI (as stated) | myosh (as stated) | This repository |
|---|---|---|---|
| P&ID and isometric digitization | Yes: symbol, tag and connection extraction, "Super P&ID", 25,000+ drawings digitized, 3D model from isometrics, fabrication packs | No | **Partial.** `extract_pid` drafts a topology with a vision LLM (every unit flagged for sign-off), with reconcile rules and precision/recall scoring against a ground-truth file. No trained symbol detector, no isometrics, no 3D. DEXPI import and export are built and round-trip checked with pyDEXPI only |
| Heat and mass balance and data sheet extraction | Yes: data sheets and H&MB mapped to streams and units | No | **Have.** H&MB from CSV, vector PDF and scanned PDF (OCR with a low-confidence review gate); merge with the P&ID takes numbers from the H&MB only and reports conflicts |
| Flowsheet generation for a simulator | Yes: HYSYS flowsheet configured from P&IDs and data sheets (vendor says days, not weeks) | No | **Partial.** Writes a validated flowsheet to HYSYS through COM (never run against a real HYSYS here), to DWSIM (run live on a real server) and to Aspen (never run against real Aspen). Writes are gated (`confirm=true`), only independent specs are written and read-back is audited |
| Checking the model against published or independent references | Not mentioned | Not applicable | **Have, and the distinguishing strength.** 20 reference cases (18 built and run on DWSIM, 2 recorded as blocked answer keys; references are published values or independent calculations from CoolProp and NIST-JANAF, and 5 are constructed exercises, flagged as such), a ledger of 153 run rows, scenario by property-package matrices, classified findings, tolerances fixed before running, and records of where a source disagrees with itself. None is human-reviewed yet |
| Design-criteria guardrails | Not mentioned | Compliance registers and legislation tracking, not simulation checks | **Partial.** OSHA 29 CFR 1910.119 and 1910.106 rules evaluated on every run; API and NFPA rules registered but inactive until licensed numbers are supplied; advisory vessel, pump and valve rules from forum and trade sources. No real plant limits are loaded |
| Document intelligence: cross-document graph, revision tracking, change propagation | Yes: the contextual graph, version tracking, automatic downstream impact | Change management as a guided workflow, not a document graph | **None.** No document store, no revision history, no impact tracing |
| Data sheet cross-check (design against EPC against vendor) | Yes | No | **None** as a feature. The P&ID against H&MB conflict report is the nearest piece |
| Natural-language engineering Q&A and agentic workflows | Yes ("Junior", grounded in the graph, cites the source) | AI inside records and forms (summaries, patterns, control suggestions) | **Partial.** The MCP server lets an LLM client call 46 tools, so questions about a loaded flowsheet can be answered and acted on, but there is no document corpus, no retrieval over drawings and no source citations |
| HAZOP and root cause analysis | Yes: HAZOP reports digitized into the graph, anomaly to origin tracing, safety barrier status | Digital bow-tie, critical control management with automatic control verification records | **Partial (added after this comparison was first written).** A deviation runner exists (`casebook_hazop`): sized guide-word deviations on feed streams, solved on DWSIM, consequences from the simulation and the declared limits, a worksheet with the team's causes and safeguards. A small cause and safeguard rules store (30 causes from two open sources, all marked unreviewed) supplies suggestions. Draft nodes can be derived from a casebook case or an extracted P&ID topology (architecture doc section 29), with sizes only from the team and every extraction flag carried forward. No SIL/LOPA, no bow-tie, no root cause analysis on live data |
| Predictive operations: alarm intelligence, condition-based maintenance, soft sensors, optimization recommendations | Yes ("Brains", with historian and alarm data) | Analytics and trends on EHS records | **None for live data.** Screening models only: refinery yield balance, boiler and utilities balance, steam demand, relief sizing; no historian connection |
| EHS management: incidents, actions, audits, inspections, registers (chemicals, asbestos, equipment), training, mobile app | No | Yes, 50+ modules, configurable, mobile app, integrations, custom modules | **None.** Out of scope for this repository |
| Governance: users, permissions, audit trail | Not stated on the pages read | Yes (permissions, audit trail, "human reviewed") | **Partial.** A ledger of runs with case hashes, and sign-off gates, but no users or permissions |
| Evidence that the numbers are right | Vendor-stated percentages, no method shown | Vendor-stated savings, no method shown | **Have, within limits.** Every case states its source, licence and what was and was not read; tests include seeded-fault checks; many sources' own arithmetic slips were found. Cases stay at `built` until a person signs them off (none has been) |

## Where this repository falls short
1. No connected document model (graph, revisions, change impact) or document Q&A: the platform layer Drishya sells.
2. Diagram understanding is draft quality: an LLM topology draft with reconcile rules, no symbol model and no isometrics.
3. The simulator writers are tested live only on DWSIM; HYSYS and Aspen paths are unproven here.
4. HAZOP: a deviation runner, a small rules store and P&ID-derived draft nodes now exist (two short open sources), but no large cause or safeguard knowledge base, no SIL/LOPA or bow-tie, no operations data, no EHS workflows, no interface or user management.

## Where it differs in a way that matters
- It runs on free and open parts (DWSIM, CoolProp) and records, per case, how the reference was obtained and what disagrees.
- Claims are limited to what a test or a live run supports; the vendor pages give percentages without method.
- Every simulator write is gated and read back; extraction output is always marked for engineer sign-off.

## Candidate next builds, in order of fit
1. ~~HAZOP deviation runner~~ built (architecture doc section 27).
2. ~~HAZOP and safeguard rules as data~~ built in small form (architecture doc section 28); a larger store needs sources that are not open.
2b. ~~P&ID-derived HAZOP nodes~~ built (architecture doc section 29).
3. **Data-sheet attribute mismatch check**: compare equipment attributes across the P&ID, the H&MB and a vendor sheet using the existing merge and reconcile code.
4. **Revision tracking and change impact** for the flowsheet and cases (a small step toward the graph).
Items such as alarm intelligence, condition-based maintenance and EHS records need live data or a multi-user store and would belong in a different product.
