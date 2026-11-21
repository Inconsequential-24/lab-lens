import pytest
from PIL import Image, ImageDraw, ImageFont

from lablens import input_guard, redact

TEXT = """Ms. Lakshmi Reddy
Age / Sex   : 28 YRS / F
Referred by : Dr. A. Qureshi (MD)
Reg. no.    : SYN616682
Phone: +91 98765 43210
Email: someone@example.com
HEMOGLOBIN
11.3
g/dL
12.0 - 15.0"""


def test_text_redaction_removes_pii_keeps_results():
    out, n = redact.redact_text(TEXT)
    for pii in ("Lakshmi", "Qureshi", "SYN616682", "98765", "someone@"):
        assert pii not in out
    for keep in ("Age / Sex", "28 YRS / F", "HEMOGLOBIN", "11.3", "12.0 - 15.0", "g/dL"):
        assert keep in out
    assert n >= 5


def test_source_pdf_redaction():
    data = open("data/reports/source/D02.pdf", "rb").read()
    g = input_guard.check(data)
    doc = redact.redact_pii(data, "pdf", g.text)
    assert doc.kind == "text" and "Lakshmi" not in doc.text and "SYN616682" not in doc.text
    assert "79.2" in doc.text


def test_pii_boxes_label_and_value_on_same_line():
    boxes = [("Name :", (0, 0, 50, 20)), ("Asha Rao", (60, 0, 140, 20)),
             ("Hemoglobin 13.2", (0, 100, 150, 120)), ("Ph: 9876543210", (0, 40, 120, 60))]
    hits = redact.pii_boxes(boxes)
    assert (60, 0, 140, 20) in hits and (0, 40, 120, 60) in hits
    assert (0, 100, 150, 120) not in hits


def test_header_band_masked_without_ocr():
    im = Image.new("RGB", (100, 100), "white")
    out, _ = redact.redact_image(im, use_ocr=False)
    assert out.getpixel((50, 5)) == (0, 0, 0) and out.getpixel((50, 90)) == (255, 255, 255)


def test_ocr_redaction_on_synthetic_image():
    im = Image.new("RGB", (900, 600), "white")
    d = ImageDraw.Draw(im)
    f = ImageFont.load_default(28)
    d.text((10, 200), "Patient Name : Ms. Asha Rao", fill="black", font=f)
    d.text((10, 300), "Mobile: 9876543210", fill="black", font=f)
    d.text((10, 450), "Hemoglobin 13.2 g/dL", fill="black", font=f)
    out, n = redact.redact_image(im)
    assert n >= 3  # header band + two PII boxes
    texts = " ".join(t for t, _ in redact._ocr_boxes(out))
    assert "Asha" not in texts and "9876543210" not in texts and "13.2" in texts


@pytest.mark.parametrize("text,leak", [
    ("Age: 34 Name: Rahul Sharma\nHemoglobin 13.0 g/dL", "Rahul"),
    ("Patient Name\nRahul Sharma\nHemoglobin\n13.0", "Rahul"),
    ("Name Rahul Verma\nHemoglobin\n13.0", "Rahul"),
    ("Address: 12 MG Road\nSector 5, Andheri\nMumbai\n\nHemoglobin\n13.0", "Andheri"),
    ("Rahul Sharma\nHemoglobin\n13.0", "Rahul"),
    ("राहुल शर्मा\nHemoglobin\n13.0", "राहुल"),
])
def test_header_and_label_leaks(text, leak):
    out, _ = redact.redact_text(text)
    assert leak not in out and "Hemoglobin" in out and "13.0" in out


def test_label_leaks_after_first_test_row():
    out, _ = redact.redact_text("Hemoglobin\n13.0\nAge: 34 Name: Rahul Sharma\nName Ravi\n"
                                "Patient Name\nSita Rao\nAddress: 1 Main St\nLine Two\n\nMCV\n90")
    for leak in ("Rahul", "Ravi", "Sita", "Main St", "Line Two"):
        assert leak not in out
    assert "Age: 34" in out and "MCV\n90" in out


def test_all_source_pdfs_mask_patient_and_keep_rows():
    import json
    from pathlib import Path
    for gt in sorted(Path("data/ground_truth").glob("D*.json")):
        d = json.loads(gt.read_text())
        text = input_guard.check(Path(d["source_pdf"]).read_bytes()).text
        out, _ = redact.redact_text(text)
        p = d["patient"]
        for part in p["name"].replace(".", " ").split():
            if len(part) > 2:
                assert part not in out, (gt.name, part)
        assert p["patient_id"] not in out
        kept = [t for t in d["tests"] if t["printed_name"] in out and t["value"]["raw"] in out]
        assert len(kept) == len(d["tests"]), gt.name


def test_redact_pii_refuses_oversized_inputs():
    import io
    buf = io.BytesIO()
    Image.new("1", (12001, 1)).save(buf, format="PNG")
    with pytest.raises(ValueError):
        redact.redact_pii(buf.getvalue(), "image", use_ocr=False)
