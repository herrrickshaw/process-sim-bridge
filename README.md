# process-sim-bridge

Tools that move process-engineering data (Heat & Mass Balance tables, P&IDs, datasheets) into simulators with fewer
transcription errors, plus a valve-sizing calculator. Python 3.11+, standard library only (optional extras noted below).

| Package | What it does |
|---|---|
| [`hysys_bridge`](hysys_bridge/README.md) | H&MB (CSV / vector PDF / OCR) and P&ID topology → validated flowsheet IR → Aspen HYSYS (COM or spreadsheet link) with read-back audit; DEXPI P&ID XML and DEXPI Process JSON export; MCP server. |
| `valve_sizing` | Relief/safety valve sizing from MAWP (API 520 Part I: gas, steam, liquid, fire case) and control valve sizing (IEC 60534), CLI + tests. |

## Status — read before relying on any of it
- **Nothing has been run against a real Aspen HYSYS.** The COM backend and the spreadsheet link are tested only against mocks.
  Run a small known case and treat any read-back or propagation mismatch as a reason to distrust the result.
- DEXPI output loads in pyDEXPI 2.1.0 (checked), but has not been validated against the Proteus schema or a commercial P&ID tool.
- `valve_sizing` is checked against hand calculations only, not a published worked example or vendor software.
  Calculation results are not a substitute for a qualified engineer's review and the valve manufacturer's sizing.
- `pid_extract.py` (vision-LLM P&ID topology) and `ocr.py` produce **drafts** that must be reviewed; they have not been run live.
- No proprietary data is included; the only sample (`hysys_bridge/sample/hmb.csv`) is synthetic.

## Run the tests
```bash
python3 -m unittest discover -s hysys_bridge/tests -t .
python3 -m unittest discover -s valve_sizing/tests -t .
```
Optional: `pip install pydexpi` enables the DEXPI process-model export and its tests.

## Licence
MIT — see [LICENSE](LICENSE).
