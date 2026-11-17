"""hysys_bridge: H&MB / datasheet / P&ID  ->  validated IR  ->  Aspen HYSYS (COM).

Pipeline (mirrors the layered design of arXiv 2603.24629, Sketch2Simulation):
  extract_hmb / pid_extract  -> ir.Flowsheet
  normalize                  -> explicit mixers/splitters (rule-based, no LLM)
  validate                   -> units, bounds, composition sums, mass balance
  hysys_writer               -> write SPECS only, read back every value
  hmb_check                  -> compare HYSYS-calculated vs H&MB-stated values
"""
