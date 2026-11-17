"""Scanned H&MB -> rows, with per-cell OCR confidence and a mandatory review list.

words_to_rows() is pure (testable). ocr_pdf() needs: pip install pymupdf pytesseract + tesseract.
Every cell under CONF_MIN, or that fails numeric sanity, goes to the review list; the CLI
refuses to write to HYSYS until a human has corrected the CSV (review.csv -> fixed rows).
"""
from __future__ import annotations
from dataclasses import dataclass
import re

CONF_MIN = 95.0
Word = tuple  # (text, x0, x1, top, conf)


@dataclass
class Cell:
    text: str
    conf: float


def _cluster(vals: list[float], gap: float) -> list[float]:
    vals = sorted(vals); out, cur = [], [vals[0]]
    for v in vals[1:]:
        if v - cur[-1] > gap: out.append(sum(cur) / len(cur)); cur = []
        cur.append(v)
    out.append(sum(cur) / len(cur)); return out


def words_to_rows(words: list[Word], row_gap=8.0, col_gap=25.0):
    """Group OCR words into a grid. Rows by 'top', columns by left edge of numeric-ish words;
    the first column (labels) may contain several words and is joined."""
    if not words: return [], []
    rows_y = _cluster([w[3] for w in words], row_gap)
    by_row: dict[int, list[Word]] = {i: [] for i in range(len(rows_y))}
    for w in words:
        by_row[min(range(len(rows_y)), key=lambda i: abs(rows_y[i] - w[3]))].append(w)
    numeric = re.compile(r"^[-+<>~]?[\d,.]+(?:[eE][-+]?\d+)?$|^[-—–]$")
    xs = [w[1] for r in by_row.values() for w in r if numeric.match(w[0])]
    if not xs: return [], []
    cols_x = _cluster(xs, col_gap)
    first_col_end = cols_x[0] - col_gap / 2
    grid, review = [], []
    for ri in range(len(rows_y)):
        ws = sorted(by_row[ri], key=lambda w: w[1])
        label = [w for w in ws if w[1] < first_col_end]
        cells = [Cell("", 100.0) for _ in cols_x]
        for w in ws:
            if w[1] >= first_col_end:
                ci = min(range(len(cols_x)), key=lambda i: abs(cols_x[i] - w[1]))
                cells[ci] = Cell((cells[ci].text + " " + w[0]).strip(), min(cells[ci].conf, w[4]))
        lab = " ".join(w[0] for w in label)
        row = [lab] + [c.text for c in cells]
        grid.append(row)
        lab_conf = min([w[4] for w in label], default=100.0)
        if lab_conf < CONF_MIN: review.append((len(grid) - 1, 0, lab, lab_conf))
        for ci, c in enumerate(cells, start=1):
            if c.text and c.conf < CONF_MIN: review.append((len(grid) - 1, ci, c.text, c.conf))
    return grid, review


def ocr_pdf(path: str, page: int = 1, dpi: int = 300):                 # pragma: no cover
    import fitz, pytesseract
    from PIL import Image
    import io
    pix = fitz.open(path)[page - 1].get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    d = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config="--psm 6")
    words = [(d["text"][i], d["left"][i], d["left"][i] + d["width"][i], d["top"][i], float(d["conf"][i]))
             for i in range(len(d["text"])) if d["text"][i].strip() and float(d["conf"][i]) >= 0]
    return words_to_rows(words, row_gap=dpi / 40, col_gap=dpi / 12)
