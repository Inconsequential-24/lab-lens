"""redact_pii: keep name, IDs, phone, address and doctor out of prompts and logs (PLAN.md 4)."""
from __future__ import annotations

import base64
import io
import re
from functools import lru_cache

from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from lablens.input_guard import MAX_PAGES, MAX_PIXELS, MAX_SIDE, page_fits, render_scale

HEADER_BAND = 0.22  # fraction of page height masked on images (letterhead + patient grid)
MASK = "[REDACTED]"

_LABELS = (r"patient\s*name|name|patient\s*id|patient|uhid|mrn|reg(?:istration)?\.?\s*no\.?|"
           r"lab\s*(?:id|no\.?)|sample\s*(?:id|no\.?)|accession\s*no\.?|barcode|visit\s*no\.?|"
           r"ref(?:erred)?\.?\s*by|referring\s*doctor|consultant|doctor|phone|mobile|mob\.?|"
           r"tel\.?|contact|address|addr\.?|e-?mail")
LABEL_LINE = re.compile(rf"^(\s*(?:{_LABELS})\s*[:\-])\s*(.+)$", re.I | re.M)
LABEL_ONLY = re.compile(rf"^\s*(?:{_LABELS})\s*[:\-]?\s*$", re.I)
SEP_LABEL = re.compile(rf"(?<!\w)(?:{_LABELS})\s*[:\-]", re.I)  # label + ":"/"-" anywhere in a line
START_LABEL = re.compile(rf"^\s*(?:{_LABELS})\s+(?=\S)", re.I)  # "Name Rahul" (no colon)
ADDRESS = re.compile(r"(?<!\w)addr(?:ess|\.)?", re.I)
# Non-identifying header fields kept for extraction (report_date, sex-specific ranges); no DOB.
SAFE_FIELD = re.compile(r"^\s*(?:age|sex|gender|sample\s*type|report\s*status|"
                        r"(?!.*birth)[a-z ]{0,20}date)\b[^:]*(?::.*)?$", re.I)
PAGE_MARK = re.compile(r"^\[page \d+\]$")
COLUMN_WORDS = {"test", "name", "tests", "investigation", "parameter", "result", "results", "value",
                "observed", "unit", "units", "bio", "ref", "reference", "range", "interval",
                "method", "flag", "biological"}
HONORIFIC = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr|Master|Baby|Smt|Shri)\.?[ \t]+[A-Z][\w.'-]*"
                       r"(?:[ \t]+[A-Z][\w.'-]*){0,3}")
PHONE = re.compile(r"(?:\+91[\s-]?)?(?<!\d)[6-9]\d{4}[\s-]?\d{5}(?!\d)|\+\d{1,3}[\s-]?\d{3,5}[\s-]?\d{4,6}")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL = re.compile(r"\b(?:https?://|www\.)\S+", re.I)
ID_TOKEN = re.compile(r"\b[A-Z]{2,5}[-/]?\d{5,}\b")  # SYN616682, UHID-0012345
PINCODE = re.compile(r"\b\d{3}\s?\d{3}\b(?=\s*$)", re.M)  # 6-digit PIN at a line end


class RedactedDoc(BaseModel):
    kind: str  # "text" (digital PDF) or "image"
    text: str = ""
    images_b64: list[str] = Field(default_factory=list)  # PNG, one per page
    mime: str = "image/png"
    redactions: int = 0


def _is_test_row(line: str) -> bool:
    """Line starts with a known test name or alias (reference/panels.yaml via validate)."""
    from lablens.validate import _alias_index, norm_name
    idx = _alias_index()
    toks = norm_name(line).split()
    return any(" ".join(toks[:k]) in idx for k in range(min(len(toks), 8), 0, -1))


def _is_column_header(line: str) -> bool:
    words = set(re.sub(r"[^a-z]+", " ", line.lower()).split())
    return bool(words) and words <= COLUMN_WORDS


def _mask_header_block(lines: list[str]) -> tuple[list[str], int]:
    """Per page: mask every line before the first recognised test row (patient/header block)."""
    out, n, i = [], 0, 0
    while i < len(lines):
        j = i + 1  # page = [page N] marker (if any) .. next marker
        while j < len(lines) and not PAGE_MARK.match(lines[j].strip()):
            j += 1
        page = lines[i:j]
        first = next((k for k, ln in enumerate(page) if _is_test_row(ln)), None)
        safe_prev = False
        for k, ln in enumerate(page):
            safe = bool(SAFE_FIELD.match(ln)) and not SEP_LABEL.search(ln.split(":", 1)[-1])
            keep = (first is None or k >= first or not ln.strip() or PAGE_MARK.match(ln.strip())
                    or _is_column_header(ln) or safe or (safe_prev and ln.lstrip().startswith(":")))
            safe_prev = safe and ":" not in ln
            out.append(ln if keep else MASK)
            n += not keep
        i = j
    return out, n


def _redact_labels(lines: list[str]) -> tuple[list[str], int]:
    """Label values anywhere: mid-line, no colon, value on the next line, multi-line addresses."""
    out, n, pending, address = [], 0, False, False
    for ln in lines:
        if not ln.strip():
            out.append(ln)
            address = False  # a blank line ends an address block
            continue
        seps = list(SEP_LABEL.finditer(ln))
        if (pending or address) and not seps and not START_LABEL.match(ln) and not LABEL_ONLY.match(ln):
            out.append(MASK)
            n += 1
            pending = False
            continue
        pending, address = False, False
        if LABEL_ONLY.match(ln):
            out.append(ln)
            pending, address = True, bool(ADDRESS.search(ln))
            continue
        if not seps:
            m = START_LABEL.match(ln)
            if m:
                out.append(m.group(0) + MASK)
                n += 1
                address = bool(ADDRESS.search(m.group(0)))
            else:
                out.append(ln)
            continue
        parts, pos = [ln[:seps[0].start()], ], 0
        for a, b in zip(seps, seps[1:] + [None]):
            value = ln[a.end(): b.start() if b else len(ln)]
            parts.append(a.group(0) + (f" {MASK} " if value.strip() else value))
            n += bool(value.strip())
        out.append("".join(parts).rstrip())
        last = seps[-1]
        pending = not ln[last.end():].strip()
        address = any(ADDRESS.search(s.group(0)) for s in seps)
    return out, n


def redact_text(text: str) -> tuple[str, int]:
    count = 0

    def sub(pattern: re.Pattern, repl, s: str) -> str:
        nonlocal count
        s, n = pattern.subn(repl, s)
        count += n
        return s

    lines, n1 = _mask_header_block(text.split("\n"))
    lines, n2 = _redact_labels(lines)
    count += n1 + n2
    text = "\n".join(lines)
    for pat in (EMAIL, URL, PHONE, ID_TOKEN, HONORIFIC, PINCODE):
        text = sub(pat, MASK, text)
    return text, count


def _is_pii(txt: str) -> bool:
    return bool(SEP_LABEL.search(txt) or START_LABEL.match(txt) or HONORIFIC.search(txt) or PHONE.search(txt)
                or EMAIL.search(txt) or ID_TOKEN.search(txt))


@lru_cache(maxsize=1)
def _ocr():
    from rapidocr import RapidOCR  # lazy: model load is slow and only needed for images
    return RapidOCR()


def _ocr_boxes(im: Image.Image) -> list[tuple[str, tuple[float, float, float, float]]]:
    import numpy as np
    out = _ocr()(np.array(im.convert("RGB")))
    if out.boxes is None or out.txts is None:
        return []
    boxes = []
    for txt, pts in zip(out.txts, out.boxes):
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        boxes.append((txt, (min(xs), min(ys), max(xs), max(ys))))
    return boxes


def pii_boxes(boxes: list[tuple[str, tuple]]) -> list[tuple]:
    """Boxes holding PII, plus the value box right of a bare label on the same line."""
    hits = []
    for txt, b in boxes:
        if _is_pii(txt):
            hits.append(b)
        if LABEL_ONLY.match(txt):
            mid = (b[1] + b[3]) / 2
            right = [x for _, x in boxes if x[0] > b[2] and x[1] <= mid <= x[3]]
            if right:
                hits.append(min(right, key=lambda x: x[0]))
    return hits


def redact_image(im: Image.Image, use_ocr: bool = True) -> tuple[Image.Image, int]:
    im = im.convert("RGB")
    draw = ImageDraw.Draw(im)
    w, h = im.size
    draw.rectangle([0, 0, w, int(h * HEADER_BAND)], fill="black")
    n = 1
    if use_ocr:
        for b in pii_boxes(_ocr_boxes(im)):
            draw.rectangle([b[0] - 2, b[1] - 2, b[2] + 2, b[3] + 2], fill="black")
            n += 1
    return im, n


def _png_b64(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def redact_pii(data: bytes, kind: str, text_layer: str = "", use_ocr: bool = True) -> RedactedDoc:
    if kind == "pdf" and text_layer.strip():
        red, n = redact_text(text_layer)
        return RedactedDoc(kind="text", text=red, redactions=n)
    if kind == "pdf":  # scanned PDF: render pages, then the image path
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(data)
        if len(pdf) > MAX_PAGES or not all(page_fits(*pdf[i].get_size()) for i in range(len(pdf))):
            raise ValueError("page_too_large")  # defence in depth; input_guard rejects first
        pages = [pdf[i].render(scale=render_scale(*pdf[i].get_size())).to_pil() for i in range(len(pdf))]
    else:
        im = Image.open(io.BytesIO(data))
        if im.width * im.height > MAX_PIXELS or max(im.size) > MAX_SIDE:
            raise ValueError("image_too_large")  # defence in depth; input_guard rejects first
        pages = [im]
    out, total = [], 0
    for page in pages:
        im, n = redact_image(page, use_ocr)
        out.append(_png_b64(im))
        total += n
    return RedactedDoc(kind="image", images_b64=out, redactions=total)
