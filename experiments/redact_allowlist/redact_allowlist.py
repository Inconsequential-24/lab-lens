"""Allow-list redaction: decide what is ALLOWED to reach the LLM; everything else is dropped.

Detached experiment. Reads reference/panels.yaml (test names) read-only; imports nothing from lablens.

Text path (digital PDF text layer):
  1. Fields are rebuilt, not copied: age, sex and the report date are parsed out and re-emitted as
     "Age: 34 YRS" / "Sex: F" / "Report date: 17/09/2026". The line they came from is never sent.
  2. Result rows are rebuilt from parsed parts (name, flag, value, unit, range). A row needs a test
     name followed by a numeric value and a known unit; anything trailing the known name is cut.
  3. Section titles and column headers come from a fixed vocabulary.
  4. Everything else (letterhead, addresses, notes, footers, signatures, URLs) is dropped by default.
  5. Validator: every outgoing line is re-scanned for PII patterns and non-ASCII script; a hit drops
     the line and is counted as `blocked`.
Image path (scans): OCR -> the same classifier per visual line -> the kept OCR boxes are copied onto a
blank page (polygon masks). Text that OCR never detected is never copied.

mode="lenient": unknown test names are kept when the row structure (value + known unit) is present.
mode="strict":  only names in the test vocabulary are kept (max privacy, unknown tests are dropped).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]

UNITS = {u.lower() for u in [
    "g/dL", "mg/dL", "%", "fL", "pg", "U/L", "IU/L", "10^3/µL", "10^6/µL", "10^3/uL", "10^6/uL", "ng/mL", "pg/mL",
    "µg/dL", "ug/dL", "µIU/mL", "uIU/mL", "mIU/L", "mg/L", "mmol/L", "mEq/L", "ratio", "cells/µL", "/µL", "thou/mm3",
    "mill/mm3", "lakhs/cumm", "/cumm", "sec", "mm/hr", "ng/dL", "nmol/L", "g/L", "U/mL", "µmol/L", "umol/L", "mU/L"]}
TITLES = ["haematology", "hematology", "biochemistry", "immunoassay", "serology", "clinical pathology", "complete blood count",
          "lipid profile", "liver function test", "kidney function test", "thyroid profile", "glycosylated haemoglobin",
          "glycosylated hemoglobin", "routine chemistry", "urine routine", "vitamin profile"]
COLUMN_WORDS = {"test", "tests", "name", "investigation", "parameter", "result", "results", "value", "unit", "units",
                "reference", "range", "ref", "interval", "biological", "observed", "flag", "method"}
FLAG = re.compile(r"^(?:L|H|LL|HH|Low|High|\*|A)$", re.I)
NUM = r"[<>≤≥]?\s*\d+(?:\.\d+)?"
VALUE = re.compile(rf"^{NUM}$")
RANGE = re.compile(rf"^(?:{NUM}\s*[-–]\s*{NUM}|[<>≤≥]\s*\d+(?:\.\d+)?|(?:upto|up to)\s*\d+(?:\.\d+)?)$", re.I)
NAME_LIKE = re.compile(r"^[A-Za-z][A-Za-z0-9 ()/,.\-+:]{1,60}$")
STOP = re.compile(r"(?:\bc/o\b|\bpatient\b|\bpt\b\.?|\bref(?:erred)?\.?\s*by\b|\b(?:mr|mrs|ms|dr|miss|master|baby|smt|shri)\b\.?|\d{5,})", re.I)
# Fields
AGE_SEX = re.compile(r"(?<!\d)(\d{1,3})\s*(?:Y|YR|YRS|YEARS?)\b[\s/,|]*(M|F|MALE|FEMALE)\b", re.I)
AGE = re.compile(r"(?:\bage\b[^:\n]*?:\s*|(?<![\d/-]))(\d{1,3})\s*(?:Y|YR|YRS|YEARS?)\b", re.I)
SEX = re.compile(r"\b(?:sex|gender)\s*[:\-]\s*(M|F|MALE|FEMALE)\b", re.I)
DATE = r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|\d{4}-\d{2}-\d{2})"
DATE_LABELS = [("reported", re.compile(rf"\breport(?:ed)?\s*(?:on|date)?\s*[:\-]?\s*{DATE}", re.I)),
               ("collected", re.compile(rf"\b(?:collected|collection|sample)\s*(?:on|date)?\s*[:\-]?\s*{DATE}", re.I)),
               ("registered", re.compile(rf"\bregistered\s*(?:on)?\s*[:\-]?\s*{DATE}", re.I))]
# Validator patterns (second layer)
PII_PATTERNS = {
    "digits": re.compile(r"\d[\d\s\-()]{6,}\d"),           # phone, Aadhaar, barcodes, long IDs
    "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "handle_url": re.compile(r"@\w+|https?://|www\.|\.\w{2,3}/\S", re.I),
    "id_token": re.compile(r"\b[A-Z]{2,5}[-/]?\d{4,}\b"),
    "honorific": re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Miss|Master|Baby|Smt|Shri)\b\.?", re.I),
    "label": re.compile(r"\b(?:name|address|mobile|phone|ph|tel|email|uhid|mrn|aadhaar|abha|policy|patient|dob|birth)\b", re.I),
    "non_latin": re.compile(r"[^\x00-\x7Fµ≤≥–]"),
}


@lru_cache(maxsize=1)
def vocab() -> list[str]:
    tests = yaml.safe_load((REPO / "reference" / "panels.yaml").read_text())["tests"]
    names = {_norm(n) for t in tests.values() for n in [t["name"], *t.get("aliases", [])]}
    return sorted((n for n in names if n), key=len, reverse=True)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower().replace("µ", "u")).strip()


def pii_hits(line: str, allow_dates=False) -> list[str]:
    hits = [k for k, p in PII_PATTERNS.items() if p.search(line)]
    if allow_dates and hits == ["digits"] and re.fullmatch(rf"Report date: {DATE}", line):
        return []
    return hits


def clean_name(raw: str, mode: str) -> str | None:
    """Return the allowed part of a test-name cell, or None. Known names win; trailing extras are cut."""
    raw = raw.strip()
    n = _norm(raw)
    toks = n.split()
    for alias in vocab():
        a = alias.split()
        if toks[:len(a)] != a:
            continue
        words, kept = raw.split(), []
        for w in words:
            if len(_norm(" ".join(kept)).split()) >= len(a):
                break
            kept.append(w)
        known = " ".join(kept)
        rest = raw[len(known):].strip()
        m = re.match(r"^\(([A-Za-z0-9 .\-/]{1,8})\)$", rest)
        if not rest or m:
            return known + (f" ({m.group(1)})" if m else "")
        stop = STOP.search(rest)
        if stop or pii_hits(rest):
            # PII-looking tail after a known name: cut it, keep the known part only
            return known
        # a clean tail means a DIFFERENT, longer test name (e.g. "... HEMOGLOBIN CONCENTRATION");
        # truncating would silently turn MCHC into MCH, so treat the whole thing as unknown
        break
    if mode == "strict" or not NAME_LIKE.match(raw):
        return None
    stop = STOP.search(raw)
    name = raw[:stop.start()].strip(" -,:(") if stop else raw
    name = re.sub(r"\(([^)]{9,})\)", "", name).strip()           # long parentheticals are not abbreviations
    if not name or pii_hits(name) or len(name.split()) > 8 or not re.search(r"[A-Za-z]{2}", name):
        return None
    return name


def is_title(line: str) -> bool:
    n = _norm(line)
    if not n:
        return False
    if set(n.split()) <= COLUMN_WORDS:
        return True
    return any(n.startswith(t) and len(n.split()) - len(t.split()) <= 3 for t in TITLES)


def is_unit(tok: str) -> bool:
    return tok.strip().lower().replace("\u03bc", "µ") in UNITS


@dataclass
class Result:
    text: str
    kept_rows: int = 0
    dropped_lines: int = 0
    blocked: list[str] = field(default_factory=list)
    fields: dict = field(default_factory=dict)


def extract_fields(lines: list[str]) -> dict:
    """Age, sex and one report date, parsed from anywhere on the page. DOB-style dates are never used."""
    f: dict = {}
    for ln in lines:
        if "age" not in f or "sex" not in f:
            m = AGE_SEX.search(ln)
            if m:
                f.setdefault("age", m.group(1)); f.setdefault("sex", m.group(2)[0].upper())
        if "age" not in f:
            m = AGE.search(ln)
            if m and not re.search(r"\b(?:dob|birth)\b", ln[:m.start()], re.I) or (m and "/" in ln[:m.start()] and "age" in ln.lower()):
                f["age"] = m.group(1)
        if "sex" not in f:
            m = SEX.search(ln)
            if m:
                f["sex"] = m.group(1)[0].upper()
    for key, pat in DATE_LABELS:
        for ln in lines:
            m = pat.search(ln)
            if m:
                f["report_date"] = m.group(1)
                return f
    return f


def _row_from_line(line: str, mode: str, fuzzy_unit: bool = False) -> tuple[str, str] | None:
    """Whole row on one line: NAME [FLAG] VALUE UNIT [RANGE].
    fuzzy_unit (scans only): OCR garbles units ("g/dL" -> "7p/6"), so any short token is accepted as the
    unit when a valid reference range follows it."""
    toks = line.replace("\u03bc", "µ").split()
    for i in range(1, len(toks)):
        if not VALUE.match(toks[i]):
            continue
        j = i + 1
        name_toks, flag = toks[:i], ""
        if FLAG.match(name_toks[-1]) and len(name_toks) > 1:
            flag, name_toks = name_toks[-1], name_toks[:-1]
        rng = " ".join(toks[j + 1:])
        unit_ok = j < len(toks) and (is_unit(toks[j]) or (fuzzy_unit and len(toks[j]) <= 8 and RANGE.match(rng or "x")))
        if unit_ok:
            name = clean_name(" ".join(name_toks), mode)
            if name and (not rng or RANGE.match(rng)):
                return " ".join(x for x in (name, flag, toks[i], toks[j], rng) if x), name
    return None


@dataclass
class Line:
    kind: str          # "title" | "row" | "field"
    text: str
    name: str = ""     # rows: the test-name part, the only free text in a row


def classify_stream(lines: list[str], mode: str = "lenient") -> tuple[list[Line], int]:
    """Cell-per-line text (what pypdf gives): NAME, [FLAG], VALUE, UNIT, [RANGE] on consecutive lines."""
    out, dropped, i = [], 0, 0
    L = [ln.strip() for ln in lines]
    while i < len(L):
        ln = L[i]
        if not ln or re.fullmatch(r"\[page \d+\]", ln):
            i += 1
            continue
        whole = _row_from_line(ln, mode)
        if whole:
            out.append(Line("row", whole[0], whole[1])); i += 1
            continue
        # try NAME (+ wrapped continuation) [FLAG] VALUE UNIT [RANGE]
        for wrap in (0, 1):
            if wrap and (i + 1 >= len(L) or is_title(L[i]) or is_title(L[i + 1])
                         or clean_name(L[i + 1], "strict") or FLAG.match(L[i + 1]) or VALUE.match(L[i + 1])):
                continue  # a header or a complete known name on the next line is not a wrapped continuation
            j = i + 1 + wrap
            name_raw = " ".join(L[i:j])
            flag = ""
            if j < len(L) and FLAG.match(L[j]):
                flag, j = L[j], j + 1
            if j + 1 < len(L) and VALUE.match(L[j]) and is_unit(L[j + 1]):
                name = clean_name(name_raw, mode)
                if name:
                    rng = L[j + 2] if j + 2 < len(L) and RANGE.match(L[j + 2]) else ""
                    out.append(Line("row", " ".join(x for x in (name, flag, L[j], L[j + 1], rng) if x), name))
                    i = j + 2 + bool(rng)
                    break
        else:
            # rows are tried first: a test can share its panel's title ("GLYCOSYLATED HEMOGLOBIN (HbA1c)")
            if is_title(ln):
                out.append(Line("title", ln))
            else:
                dropped += 1
            i += 1
    return out, dropped


def validate(ln: Line) -> list[str]:
    """Second layer. Values, units and ranges were matched structurally, so a row is checked on its
    name part; titles and fields are checked whole."""
    if ln.kind == "row":
        hits = pii_hits(ln.name)
        if PII_PATTERNS["non_latin"].search(ln.text):
            hits.append("non_latin")
        return hits
    return pii_hits(ln.text, allow_dates=ln.text.startswith("Report date:"))


def redact_text(text: str, mode: str = "lenient") -> Result:
    lines = text.split("\n")
    f = extract_fields(lines)
    body, dropped = classify_stream(lines, mode)
    head = []
    if "age" in f:
        head.append(Line("field", f"Age: {f['age']} YRS"))
    if "sex" in f:
        head.append(Line("field", f"Sex: {f['sex']}"))
    if "report_date" in f:
        head.append(Line("field", f"Report date: {f['report_date']}"))
    res = Result(text="", fields=f, dropped_lines=dropped)
    final = []
    for ln in head + body:
        hits = validate(ln)
        if hits:
            res.blocked.append(f"{ln.kind}:{','.join(hits)}")   # never log the line itself
            continue
        final.append(ln)
    res.text = "\n".join(ln.text for ln in final)
    res.kept_rows = sum(ln.kind == "row" for ln in final)
    return res


# ---------------------------------------------------------------- images
@lru_cache(maxsize=1)
def _ocr():
    from rapidocr import RapidOCR
    return RapidOCR()


def ocr_boxes(im):
    import numpy as np
    r = _ocr()(np.array(im.convert("RGB")))
    if r.boxes is None or r.txts is None:
        return []
    return [(t, [tuple(p) for p in b]) for t, b in zip(r.txts, r.boxes)]


def _skew(boxes) -> float:
    """Median slope (dy/dx) of the top edge of wide OCR boxes: the page's rotation."""
    slopes = []
    for _, q in boxes:
        (x0, y0), (x1, y1) = q[0], q[1]
        if x1 - x0 > 40:
            slopes.append((y1 - y0) / (x1 - x0))
    return sorted(slopes)[len(slopes) // 2] if slopes else 0.0


def visual_lines(boxes):
    """Group OCR boxes into rows by their deskewed vertical centre, then left to right."""
    k = _skew(boxes)

    def ycorr(q):
        cx, cy = sum(p[0] for p in q) / 4, sum(p[1] for p in q) / 4
        return cy - k * cx

    items = sorted(boxes, key=lambda b: ycorr(b[1]))
    rows: list[list] = []
    for t, q in items:
        cy = ycorr(q)
        h = max(p[1] for p in q) - min(p[1] for p in q) - abs(k) * (max(p[0] for p in q) - min(p[0] for p in q))
        if rows and abs(rows[-1][0] - cy) < max(6, 0.5 * max(h, 8)):
            rows[-1][1].append((t, q))
        else:
            rows.append([cy, [(t, q)]])
    return [sorted(r[1], key=lambda b: min(p[0] for p in b[1])) for r in rows]


FIELD_WORDS = re.compile(r"\b(?:age|sex|gender|yrs?|years?|y|m|f|male|female|reported|report|collected|collection|"
                         r"registered|on|date|am|pm)\b|[\d/:\-|,.]", re.I)


def _box_ok(t: str) -> bool:
    t = t.replace("\u03bc", "µ")
    return not pii_hits(t) or bool(VALUE.match(t) or RANGE.match(t) or is_unit(t))


def _row_prefix(ln, mode: str):
    """Longest run of boxes, from the left, that parses as a result row. Boxes after it on the same
    visual line (a side box, a margin note) are not part of the row and are not copied."""
    for k in range(len(ln), 0, -1):
        txt = " ".join(t for t, _ in ln[:k]).replace("\u03bc", "µ")
        if _row_from_line(txt, mode, fuzzy_unit=True) and not PII_PATTERNS["non_latin"].search(txt):
            return [q for t, q in ln[:k] if _box_ok(t)]
    return None


def redact_image(im, mode: str = "lenient"):
    """Return (new_image, kept_boxes, fields). Only allowed boxes are copied onto a blank page."""
    from PIL import Image, ImageDraw
    im = im.convert("RGB")
    boxes = ocr_boxes(im)
    lines = visual_lines(boxes)
    keep = []
    texts = [" ".join(t for t, _ in ln) for ln in lines]
    fields = extract_fields(texts)
    for ln, txt in zip(lines, texts):
        if is_title(txt) and not pii_hits(txt):
            keep += [q for _, q in ln]
            continue
        row_boxes = _row_prefix(ln, mode)
        if row_boxes is not None:
            keep += row_boxes
            continue
        for t, q in ln:  # field boxes: keep only if nothing but field words remain once those are removed
            if (AGE_SEX.search(t) or AGE.search(t) or SEX.search(t) or any(p.search(t) for _, p in DATE_LABELS)) \
                    and not re.search(r"[A-Za-z]{3,}", FIELD_WORDS.sub(" ", t)) and not re.search(r"\b(?:dob|birth)\b", t, re.I):
                keep.append(q)
    out = Image.new("RGB", im.size, "white")
    mask = Image.new("L", im.size, 0)
    d = ImageDraw.Draw(mask)
    for q in keep:
        d.polygon([(x, y) for x, y in q], fill=255)
    out.paste(im, (0, 0), mask)
    return out, len(keep), fields
