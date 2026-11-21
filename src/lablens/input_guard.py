"""input_guard: reject bad inputs early with stable reason codes (PLAN.md section 11 Input)."""
from __future__ import annotations

import io
import re
from typing import Literal

import pypdf
from PIL import Image
from pydantic import BaseModel

from lablens.validate import names_by_test, norm_name as _norm

MAX_BYTES = 5 * 1024 * 1024  # PLAN.md section 6
MAX_PAGES = 10
MAX_PIXELS = 40_000_000  # decompression-bomb cap per image or rendered page
MAX_SIDE = 12_000  # px, either side
RENDER_SCALE = 2  # scanned-PDF render scale used by redact (72 dpi * 2)
Image.MAX_IMAGE_PIXELS = MAX_PIXELS  # Pillow raises DecompressionBombError above 2x this
MIN_TEST_HITS = 2  # catalog test names that must appear for "is a lab report"

Reason = Literal["unsupported_file_type", "file_too_large", "empty_file", "encrypted_pdf",
                 "corrupt_pdf", "zero_pages", "too_many_pages", "corrupt_image",
                 "image_too_large", "page_too_large",
                 "not_a_lab_report"]


class GuardResult(BaseModel):
    ok: bool
    reason: Reason | None = None
    kind: Literal["pdf", "image"] | None = None
    mime: str | None = None
    pages: int = 0
    text: str = ""  # PDF text layer, unredacted; never logged


def sniff(data: bytes) -> tuple[str, str] | None:
    if data.startswith(b"%PDF-"):
        return "pdf", "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    return None


def _catalog_terms() -> set[str]:
    # skip short names like "hb": too common as substrings
    return {n for names in names_by_test().values() for n in names if len(n) >= 3}


def looks_like_lab_report(text: str) -> bool:
    """Heuristic: at least MIN_TEST_HITS known test names plus a numeric result."""
    norm = f" {_norm(text)} "
    hits = sum(1 for term in _catalog_terms() if f" {term} " in norm)
    return hits >= MIN_TEST_HITS and bool(re.search(r"\d", text))


def page_fits(w_pt: float, h_pt: float, scale: float = RENDER_SCALE) -> bool:
    """A PDF page rendered at `scale` stays within the pixel caps."""
    w, h = abs(w_pt) * scale, abs(h_pt) * scale
    return w * h <= MAX_PIXELS and max(w, h) <= MAX_SIDE


def _reject(reason: Reason, **kw) -> GuardResult:
    return GuardResult(ok=False, reason=reason, **kw)


def check(data: bytes) -> GuardResult:
    if not data:
        return _reject("empty_file")
    if len(data) > MAX_BYTES:
        return _reject("file_too_large")
    found = sniff(data)
    if found is None:
        return _reject("unsupported_file_type")
    kind, mime = found
    if kind == "image":
        try:
            with Image.open(io.BytesIO(data)) as im:
                w, h = im.size  # header only; no pixel decode
                if w * h > MAX_PIXELS or max(w, h) > MAX_SIDE:
                    return _reject("image_too_large", kind=kind, mime=mime)
                im.verify()
        except Image.DecompressionBombError:
            return _reject("image_too_large", kind=kind, mime=mime)
        except Exception:
            return _reject("corrupt_image", kind=kind, mime=mime)
        # No text layer: the lab-report check for images happens after extraction (zero rows).
        return GuardResult(ok=True, kind=kind, mime=mime, pages=1)
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            return _reject("encrypted_pdf", kind=kind, mime=mime)
        n = len(reader.pages)
    except Exception:
        return _reject("corrupt_pdf", kind=kind, mime=mime)
    if n == 0:
        return _reject("zero_pages", kind=kind, mime=mime)
    if n > MAX_PAGES:
        return _reject("too_many_pages", kind=kind, mime=mime, pages=n)
    try:
        sizes = [(float(p.mediabox.width), float(p.mediabox.height)) for p in reader.pages]
    except Exception:
        return _reject("corrupt_pdf", kind=kind, mime=mime, pages=n)
    if any(not page_fits(w, h) for w, h in sizes):
        return _reject("page_too_large", kind=kind, mime=mime, pages=n)
    try:
        pages = [p.extract_text() or "" for p in reader.pages]
    except Exception:
        return _reject("corrupt_pdf", kind=kind, mime=mime, pages=n)
    # Scanned PDFs have no text layer; only reject when there is text and it is not a report.
    text = "\n".join(f"[page {i}]\n{t}" for i, t in enumerate(pages, 1)) if any(t.strip() for t in pages) else ""
    if text and not looks_like_lab_report(text):
        return _reject("not_a_lab_report", kind=kind, mime=mime, pages=n)
    return GuardResult(ok=True, kind=kind, mime=mime, pages=n, text=text)
