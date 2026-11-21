import io

import pypdf
import pytest
from PIL import Image

from lablens import input_guard as g

SRC = "data/reports/source/D02.pdf"


def _pdf(pages=1, encrypt=False) -> bytes:
    w = pypdf.PdfWriter()
    for _ in range(pages):
        w.add_blank_page(100, 100)
    if encrypt:
        w.encrypt("pw")
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_real_source_report_accepted():
    r = g.check(open(SRC, "rb").read())
    assert r.ok and r.kind == "pdf" and r.pages == 1 and "HEMOGLOBIN" in r.text


@pytest.mark.parametrize("data,reason", [
    (b"", "empty_file"),
    (b"GIF89a....", "unsupported_file_type"),
    (b"%PDF-1.7 garbage", "corrupt_pdf"),
    (b"\x89PNG\r\n\x1a\nnot really", "corrupt_image"),
])
def test_rejections(data, reason):
    assert g.check(data).reason == reason


def test_too_large(monkeypatch):
    monkeypatch.setattr(g, "MAX_BYTES", 10)
    assert g.check(_png()).reason == "file_too_large"


def test_encrypted_and_page_limit():
    assert g.check(_pdf(encrypt=True)).reason == "encrypted_pdf"
    assert g.check(_pdf(pages=11)).reason == "too_many_pages"
    assert g.check(_pdf(pages=10)).ok  # blank (scanned-like) pages pass to the image path


def test_image_accepted():
    r = g.check(_png())
    assert r.ok and r.mime == "image/png"


def test_lab_report_heuristic():
    assert g.looks_like_lab_report("Hemoglobin 13.0 g/dL\nPlatelet Count 250")
    assert not g.looks_like_lab_report("Invoice: consultation fee 500, GST 18%")


def _huge_png_header(w=50_000, h=50_000) -> bytes:
    """Tiny file, huge declared dimensions (decompression-bomb style)."""
    import struct
    import zlib
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"")) + chunk(b"IEND", b"")


@pytest.mark.parametrize("w,h", [(50_000, 50_000), (12_001, 10), (7000, 7000)])
def test_image_too_large(w, h):
    data = _huge_png_header(w, h)
    assert len(data) < 200
    assert g.check(data).reason == "image_too_large"


def test_pdf_page_too_large():
    w = pypdf.PdfWriter()
    w.add_blank_page(width=14400, height=14400)
    buf = io.BytesIO()
    w.write(buf)
    assert g.check(buf.getvalue()).reason == "page_too_large"
    assert g.page_fits(595, 842)
