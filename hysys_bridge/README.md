# hysys_bridge
H&MB (CSV / vector PDF) -> validated IR -> Aspen HYSYS via COM, with read-back audit.
Architecture follows the layered design of arXiv 2603.24629 (Sketch2Simulation), minus the LLM
agents: here the data comes from tables, so extraction is deterministic. Add a P&ID vision
extractor later that emits the same `ir.Flowsheet` (topology only; keep it flagged for sign-off).

    python -m unittest discover -s hysys_bridge/tests -t .
    python -m hysys_bridge.cli hysys_bridge/sample/hmb.csv --mock      # any OS
    python -m hysys_bridge.cli my_hmb.pdf                              # Windows + HYSYS

Design rules: only independent specs are written; H&MB enthalpy/VF/downstream values are
compared after solve (hmb_check). Ambiguous units (bar vs barg) raise. Errors block the write.

Status: extract/normalize/validate/writer/check are tested against the Mock backend.
`backend.HysysCOM` is UNTESTED - verify TYPE_MAP and property paths on your HYSYS version.
Added: `ocr.py` (scanned H&MB; words->grid; cells <95% confidence go to review.csv and block the write
until `--accept-review`), `pid_extract.py` (two-pass vision LLM topology draft, hallucinated units rejected,
all units flagged `needs-signoff`; blocks until `--accept-topology`; `merge_values` takes numbers from the H&MB only
and reports P&ID vs H&MB topology conflicts). Grid/JSON logic is tested offline; the live Tesseract and
Anthropic API calls (`ocr_pdf`, `anthropic_ask`) are UNTESTED here.
Not done: mass->mole conversion, reactors/columns, multi-page stitching.

## P&ID scoring and reconciliation (added after reading arXiv 2411.13929 and 2109.03794)
- `pid_reconcile.py`: domain-rule checks on an extracted topology (self-loops, isolated units,
  tag vs type, tag-pattern outliers, OCR-confusable tags, per-type inlet/outlet counts, disconnected
  sub-flowsheets, recycle loops, duplicate parallel streams). Only self-loops and isolated units are auto-fixed.
- `pid_eval.py`: node/edge P/R/F1, direction flips and adjacency exact-match against a ground-truth
  flowsheet JSON (`--truth`). It does NOT reproduce the PID2Graph edge mAP (needs bounding boxes and
  detector confidences, which this LLM-based IR lacks), so don't compare numbers with the paper.
- Neither is a P&ID detector: no symbol model is trained here. Rules/metrics were written from my reading of
  the papers' reconciliation and metrics sections only, not from their code.

## DEXPI export (dexpi_export.py, dexpi_process.py)
- `--dexpi out.xml`: Proteus-style P&ID XML (topology + the few attributes a P&ID can hold: operating temperature,
  pump differential pressure, design flows/duty). Loads in pyDEXPI 2.1.0 with no errors.
- `--dexpi-process out.json`: DEXPI *Process* model via pyDEXPI (ProcessSteps, Streams with T/P/mass & volume flow,
  MaterialTemplate, Composition, specific enthalpy). Needs `pip install pydexpi`. Diagram boundaries become
  `BOUNDARY-<stream>` process steps. Round-trip checked through pyDEXPI's JSON serializer, not against any other DEXPI tool.
- The XML and the process JSON are two files: DEXPI does not put stream data in the P&ID XML.
- Equipment classes in the XML (checked against pyDEXPI 2.1.0): pump CentrifugalPump, compressor CentrifugalCompressor,
  heater/cooler HeatExchanger, separator Separator, column ProcessColumn, mixer Mixer, reactor PressureVessel (DEXPI has no
  reactor class - judgement call), unknown ProcessEquipment. Valves become GlobeValve/OperatedValve and splitters PipeTee
  *items inside segments* (not equipment); streams around them share one segment, restored by `dexpi_export.load()`.

## MCP server: link diagrams / P&ID / H&MB to Aspen HYSYS (`mcp_server.py`)
Standard-library MCP server over stdio. Add to your MCP client config (nothing is installed or changed for you):

    {"mcpServers": {"hysys-bridge": {"command": "python3", "args": ["-m", "hysys_bridge.mcp_server"],
                                     "cwd": "/path/to/process-tools"}}}

Tools: status, load_hmb, load_dexpi, load_flowsheet_json, extract_pid, summarize, normalize, validate, reconcile,
merge_pid_hmb, score, plan_specs, write_to_hysys, export_dexpi, export_dexpi_process.
Typical chain: `extract_pid` (or `load_dexpi`) -> `reconcile` -> `load_hmb` -> `merge_pid_hmb` -> `normalize` -> `validate`
-> `plan_specs` -> `write_to_hysys` (confirm=true).

A DWSIM or Aspen case belongs to the session contents it was built from. If the session is changed or removed, solving the case and every tool that uses its results refuse until you build and solve again; closing it still works.

`casebook_run` and `casebook_hazop` have no mock: they start live DWSIM only when called with `live=true` (and `DWSIM_MCP_CMD` set); `confirm=true` only controls the ledger. The `python -m hysys_bridge.casebook` command line is run by a person and needs no flag.

Each request to DWSIM has a time limit (300 s unless the operator sets `DWSIM_MCP_TIMEOUT_S`). A server that misses it is stopped and the case must be built again. Open DWSIM and Aspen cases are closed when the tool server's input ends; a server that is killed outright cannot do this. With a container runtime, stopping the client process may not stop the container: check `podman ps` after a timeout.

Every true/false argument must be a JSON boolean: text such as `"false"`, numbers and null are refused.

Safety: writes need `confirm=true` and clean validation; they go to the MOCK backend unless `live=true`, the server is
started with `HYSYS_LIVE=1`, the OS is Windows with HYSYS, and you name `case_path` (.hsc) or `use_active=true`. The tool never saves or
overwrites a case. `extract_pid` uploads the drawing to Anthropic's API and needs `confirm_upload=true` + `ANTHROPIC_API_KEY`.

Open-source references used (read, not copied; no code vendored):
- brack101/AspenPlus-MCP-Server (MIT) - shape of an MCP+COM server (Aspen Plus, not HYSYS).
- edgarsmdn/Aspen_HYSYS_Python (MIT) - HYSYS COM entry points and the CanSolve/IsSolving pattern now used in `HysysCOM.solve`.
- aspen-pysys (PyPI; licence not stated on the pages I read) - HYSYS object access naming.
- pyDEXPI - used to check the DEXPI exports.
Still UNTESTED against a real HYSYS: stream/operation creation (`MaterialStreams.Add`, `Operations.Add` type strings), `SetValue(value, unit)`.

## Spreadsheet link (spreadsheet.py) - the route that avoids unverified HYSYS API calls
`write_to_hysys method=spreadsheet` writes numbers into spreadsheet cells and lets HYSYS's own links move them, using only
what edgarsmdn/Aspen_HYSYS_Python (MIT) demonstrates: `Operations.Item(sheet).Cell(col,row).CellValue` and `Solver.CanSolve/IsSolving`.
1. `spreadsheet_layout name=... [units={...}] [path=layout.csv]` lists the rows (label, unit, which stream variable).
2. In the HYSYS case build spreadsheets `HMB_IN` (column 1 cells EXPORTED to those stream variables) and `HMB_OUT` (column 1 IMPORTS them).
   The flowsheet itself (streams, units, fluid package) must already exist: this route creates nothing.
3. `write_to_hysys name=... confirm=true method=spreadsheet live=true case_path=...hsc` (needs HYSYS_LIVE=1, Windows).
   It writes, reads every cell back, solves, then `verify_propagation` compares what was written with what HYSYS reports on
   HMB_OUT. An unlinked cell, a wrong variable or a wrong unit set shows up as a propagation failure - do not trust a case that has any.
Units default to degC, kPa absolute, kg/h, kgmole/h, m3/h, mole fractions; declare others with `units` and set the same units on the linked variables.
Mass-basis feed compositions are refused (convert first). Tested against MockSheetCase only (including a seeded kg/s-vs-kg/h mismatch); not against HYSYS.
