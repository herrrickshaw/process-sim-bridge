# Model and scenario candidates (2026-11-20)

Purpose: next models to build with the DWSIM backend and for evaluating the copilot. pdfcoffee.com was used as the source of leads, as asked.

## Provenance, read this first
- pdfcoffee.com hosts third-party uploads (student reports, textbooks, vendor guides) with a "Report DMCA / Copyright" link. Its robots.txt (checked 2026-11-20) has comments only: no disallow rules, no content-signal values; pages load normally (HTTP 200, no bot challenge).
- Most of these documents are copyrighted by their authors or publishers. Use them for process conditions (facts: flows, temperatures, pressures, duties) and for scenario ideas. Do not copy their text, tables or figures into this repo. Where a public-domain document covers the same ground (NETL, NREL), prefer that one for anything committed.
- Only the first item below was opened and read for numbers; the rest are leads taken from search-result titles and snippets, not verified.

## What the backend can build today
Verified on the real DWSIM server: pump, heater, cooler (see `hysys_bridge/dwsim/backend.py`). Mixer and splitter connect fine but their parameters are unverified; valve, compressor, flash vessel are unverified. Distillation columns and reactors are blocked or untested (the server cannot assign a column feed stage, see RESEARCH_TOOLS_AND_PAPERS.md).

## Candidates

| # | Scenario | Source (pdfcoffee) | Needs | Status |
|---|---|---|---|---|
| 1 | **Cumene alkylator feed heater (BUILT, see result below)** (benzene/propylene/cumene liquid heated before the alkylator) | [Plant Design Manuscript, phenol and acetone via cumene, HYSYS V8](https://pdfcoffee.com/plant-design-manuscript-5-pdf-free.html) | heater only | **Buildable now.** Read from its tables: stream "To Heater" 72.4 C, 34.39 bar, 13,810 kmol/h, 1,071,616 kg/h, enthalpy 7.49e8 kJ/h; "To_Alkylator" 170 C, 33.77 bar, 9.6e8 kJ/h; the report's Q-Heater100 is 210,583,601 kJ/h, which matches the enthalpy difference. Needs the composition of that stream (the extracted table text is scrambled; read it from the PDF itself). Check: DWSIM heater duty vs 2.106e8 kJ/h with PR or NRTL. |
| 2 | Same plant: pumps (Q-pump100 about 20.6 MJ/h, Q-pump102 about 65.7 MJ/h) and coolers (Q-Cooler102 0.61 GJ/h, Q-Cooler103 2.84 GJ/h) | same | pump, cooler | Buildable; stream pairs need to be matched from the table. Duties give a numeric target for each unit. |
| 3 | Same plant: cumene oxidation train (four oxidisers, energy streams Q-OX-1..4), alkylator PFR, two distillation columns, cumene hydroperoxide cleavage | same | reactors, columns | Blocked until the server can configure columns and reactors. A strong later test for the copilot. |
| 4 | Ammonia loop with recycle and purge | [Complete Aspen Plus Simulation Guide](https://pdfcoffee.com/complete-aspen-plus-simulation-guide-pdf-free.html) | reactor, flash, recycle | Needs a Recycle block and a flash; good recycle test case (recycles are where published agents struggle). Not opened. |
| 5 | Crude fractionation train | [Getting Started with Aspen Plus: Petroleum](https://pdfcoffee.com/gettingstarted-petroleum-pdf-free.html) | assay, furnace, column | Vendor tutorial. Blocked on columns; the furnace heater part is buildable. Not opened. |
| 6 | HDA (hydrodealkylation) plant: flowsheet, energy integration, rigorous simulation | [Dimian, Integrated Design and Simulation of Chemical Processes](https://pdfcoffee.com/dimian-a-2003-integrated-design-and-simulation-of-chemical-processes-pdf-free.html) | reactor, flash, columns, heat integration | Textbook (copyright): use as a design reference only. Not opened. |
| 7 | Styrene monomer section | [Chemical Process Simulation and the Aspen HYSYS Software](https://pdfcoffee.com/chemical-process-simulation-and-the-aspen-hysys-software-pdf-free.html) | reactor, heat exchange | Not opened. |
| 8 | Hysys course flowsheets (Peng-Robinson, conversion reactor) | [Aspen HYSYS course, Hameed](https://pdfcoffee.com/aspen-hysys-dr-khalid-w-hameed-biochemical-eng-dept-pdf-free.html), [Tutorial Aspen HYSYS](https://pdfcoffee.com/tutorial-aspen-hysys-pdf-free.html) | mixer, heater, reactor | Beginner exercises; useful as copilot "teach me" prompts. Not opened. |
| 9 | Ethylene plant simulation | [Process Engineering and Chemical Plant Design 2011](https://pdfcoffee.com/process-engineering-and-chemical-plant-design-2011-pdf-free.html) | columns, compression | Snippet says ethylene losses were cut to 2%; not opened. |

## Public-domain alternatives for the same ground (committable)
- DOE/NETL Baseline Vol. 1 (OSTI 1569246): more cases beyond B11A (NGCC steam cycle with HRSG, CO2-capture cases); same stream-table format as the model already built.
- NREL TP-5100-47764 (OSTI 1013269): ethanol plant, column and heat-exchanger duties (columns blocked).
- NETL case with compressors and expanders (NGCC gas turbine) for the unverified compressor type.

## Suggested order
1. Item 1 (heater, a real stream with a published duty), then item 2 (pumps/coolers). Each gives a numeric pass/fail.
2. Verify mixer, valve and flash on the real server with the NETL data, then add them to the verified list.
3. Raise the column feed-stage gap with DWSIM; then items 3, 4, 5.
4. For the copilot evaluation set, turn each solved case into a natural-language task plus a reference result.

## Result: item 1, cumene alkylator feed heater (built 2026-11-20)
`examples/cumene_alkylator_feed_heater.py` heats the report's "To Heater" stream (72.43 C, 35.40 bar abs, 1,071,616 kg/h, propylene 0.00574 mole fraction,
balance benzene) to 170 C and 34.78 bar abs on the real DWSIM server. Report heater duty: 2.106e8 kJ/h (HYSYS, NRTL).

| DWSIM package | Duty, kJ/h | vs report | Outlet phase |
|---|---|---|---|
| NRTL (same family as the report) | 2.177e8 | +3.4% | 0.8% vapour |
| Peng-Robinson | 2.054e8 | -2.5% | liquid |
| SRK | 2.103e8 | -0.1% | liquid |

Read with care: all three are within 3.5%, but the spread across packages (about 6%) is as large as the gap to the report, so SRK's near-exact match is
partly luck. Uncertainties that could account for the gap: the stream composition is reconstructed (the report's table text is scrambled; the propylene
fraction was confirmed by a mole balance, the rest is assumed benzene, giving 77.9 kg/kmol vs the report's 77.6), DWSIM and HYSYS use different
interaction parameters and enthalpy references, and the report's heat flows are quoted to three digits. NRTL puts a little vapour in the outlet where the
report shows liquid, so the NRTL propylene vapour pressure differs from HYSYS's. Pressure in the report is gauge (bar_g), converted by +1.01325 bar.
