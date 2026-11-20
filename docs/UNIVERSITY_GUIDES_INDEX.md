# University guides on simulation modelling exercises: collector and first index (2026-11-20)

## What was asked and what was built
Asked: run a collector on all university websites publishing guides on modelling exercises in simulation. "All" is not something a polite collector can do: there is no list of such sites, and the repo's own rule (CLAUDE.md, "Source fetching") is about one request per second per host and no bulk crawling. What was built instead is a bounded collector that indexes the pages you give it, plus a first seed list found by web search. It is the first stage of the paper-to-simulation pipeline (discover), pointed at teaching material.

## The collector (`hysys_bridge/casebook/collect.py`, tests `hysys_bridge/tests/test_collect.py`)
- **Index, not copy.** For each URL it records the title, content type, size, a short hash, page count (PDF), a licence hint, and counts of simulator names, unit-operation terms and exercise cues. Page text is counted in memory and discarded; none is written to disk. Course notes are copyrighted by their authors, so the index holds facts about the pages, not their content. A licence hint of "none-seen" means no notice was found in the part read, not that reuse is allowed.
- **Politeness.** At most one request per second per host (a longer `Crawl-delay` in robots.txt wins); robots.txt is read before every fetch, and a URL is fetched only if it is allowed for the collector's own agent name and for `Claude-User`; a robots file that is unreachable or answers 401/403 is treated as closed, not guessed; a 401, 403, 429 or 503, a captcha, a "request rejected" page or a login wall ends work on that host and is recorded, never bypassed; a blocked URL is not retried; one page per seed (no link following); 25 MB cap; seeds already indexed are not fetched again.
- **Seeds** are in `studies/sources/seeds.txt` (operator-controlled). Run: `python3 -m hysys_bridge.casebook.collect studies/sources/seeds.txt`. Output: `studies/sources/guides.jsonl`, one row per URL.
- **Tests:** 15 tests against a local server (robots disallow, a rule written for Claude-User, crawl delay, 403 and a 200 "request rejected" page as blocks, oversize files, one-second spacing, no text stored, no re-fetch, caps, whole-word counting); 13 hand-made mutants all caught. The first real run found a bug the tests had missed: a 244-byte WAF page ("Request Rejected") served with HTTP 200 was indexed as a guide. The pattern and a test were added and that row re-run.

## First index (21 URLs, one request each)
Seeds came from four web searches (titles and snippets only, nothing read before the run); Scribd, SlideShare, Academia and Udemy results were left out because their copyright status is unreliable.

| Outcome | Count | Hosts |
|---|---|---|
| Indexed | 14 | Washington, UC Davis, UCSB, Bucknell, King Faisal, Politecnico di Milano, Marwadi, Genoa, Saint-Joseph (Lebanon), Liege, NPTEL, BIT Mesra, FOSSEE (IIT Bombay), a Chem. Eng. Education article (Florida journals) |
| Blocked, left alone | 3 | the two University of Michigan Aspen workshop pages (HTTP 403 for this agent), and a Jordan university host that answered with a "Request Rejected" page |
| Skipped by robots | 3 | robots.txt unreachable (Nazarbayev, Seoul National, Chulalongkorn): not guessed |
| Error | 1 | University of Alberta (404, page moved) |

Most useful candidates by what the counts show (counts are mentions, not an assessment of the exercises; none of these were read):

| Source | Pages | Simulator | Unit and exercise terms that stand out |
|---|---|---|---|
| FOSSEE / SASTRA DWSIM lab manual | 58 | DWSIM (68 mentions) | heat exchanger 20, reactor 16, flash 14, heater 14, CSTR 12; 20 exercise cues; the best match for our DWSIM backend |
| University of Washington Aspen Plus tutorial | 72 | Aspen Plus | distillation 51, RadFrac 32, mixer 24, flash 22, convergence 19; 205 exercise cues (the search snippet says units end with homework and solutions) |
| King Faisal University lab manual | 162 | Aspen Plus, Excel | distillation 25, RadFrac 22, reactor 22, recycle 12, sensitivity 11 |
| UCSB HYSYS manual | 91 | HYSYS (87) | reactor 62, mixer 24, CSTR 16 |
| Liege "Introduction aux travaux numeriques" (French) | 45 | Aspen Plus, HYSYS | convergence 44, flash 31, distillation 16, design spec 9 |
| BIT Mesra CAPE/Aspen tutorials | 62 | Aspen Plus | reactor 22, RadFrac 11, compressor 9, recycle 9 |
| UC Davis Aspen modules paper | web page | Aspen Plus | recycle, sensitivity, design spec, convergence |

## What this feeds
These are leads for new reference cases of the kind already built (read the exercise, take its specification and stated answer, add an independent oracle where one exists). The DWSIM manual and the Washington tutorial cover units still not verified here (heat exchanger, CSTR, shortcut and rigorous columns, design specs). Before any case, the document has to be read in full and its licence checked: only facts (specifications, answers) go into a case file, never text, tables or figures.

## Extending it
- Add URLs to `seeds.txt`. More discovery needs searches per course or department, and a decision on following links one level deep, which is not implemented and would need a per-host cap and your go-ahead.
- Hosts that blocked or skipped are not retried automatically. A person can ask the host's owners, use a copy the author published elsewhere, or drop it.
- Index rows are facts about public pages; they are not an endorsement of the content.
