"""Synthetic lab reports with PII planted in awkward places. Detached experiment: imports nothing from lablens.

Every name, phone, address and ID below is invented. Output: dataset/*.pdf, dataset/*.png, dataset/manifest.json
(manifest = what was planted, where, plus the expected report content: rows, age, sex, report date).
"""
from __future__ import annotations

import io
import json
import math
import random
from pathlib import Path

import numpy as np
import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "dataset"
RNG = random.Random(20261123)
POPPINS = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
pdfmetrics.registerFont(TTFont("Poppins", POPPINS))

PANELS = {
    "cbc": ("HAEMATOLOGY", "COMPLETE BLOOD COUNT", [
        ("HEMOGLOBIN", "g/dL", "12.0 - 15.0", "13.1"), ("TOTAL RBC COUNT", "10^6/µL", "3.80 - 4.80", "4.35"),
        ("PACKED CELL VOLUME (PCV)", "%", "36.0 - 46.0", "40.2"), ("MCV", "fL", "83.0 - 101.0", "92.4"),
        ("MCH", "pg", "27.0 - 32.0", "30.1"), ("MCHC", "g/dL", "31.5 - 34.5", "32.6"),
        ("TOTAL LEUCOCYTE COUNT (TLC)", "10^3/µL", "4.00 - 10.00", "6.80"), ("PLATELET COUNT", "10^3/µL", "150 - 410", "251")]),
    "lipid": ("BIOCHEMISTRY", "LIPID PROFILE", [
        ("TOTAL CHOLESTEROL", "mg/dL", "< 200", "182"), ("TRIGLYCERIDES", "mg/dL", "< 150", "121"),
        ("HDL CHOLESTEROL", "mg/dL", "> 50", "54"), ("LDL CHOLESTEROL - DIRECT", "mg/dL", "< 100", "96"),
        ("VLDL CHOLESTEROL", "mg/dL", "5 - 40", "24"), ("NON-HDL CHOLESTEROL", "mg/dL", "< 130", "128")]),
    "thyroid": ("IMMUNOASSAY", "THYROID PROFILE - TOTAL", [
        ("TOTAL T3 (TRIIODOTHYRONINE)", "ng/mL", "0.8 - 2.0", "1.2"), ("TOTAL T4 (THYROXINE)", "µg/dL", "5.1 - 14.1", "8.9"),
        ("TSH (THYROID STIMULATING HORMONE)", "µIU/mL", "0.27 - 4.20", "2.31")]),
    "hba1c": ("BIOCHEMISTRY", "GLYCOSYLATED HAEMOGLOBIN (HbA1c)", [
        ("GLYCOSYLATED HEMOGLOBIN (HbA1c)", "%", "4.0 - 5.6", "5.4"), ("ESTIMATED AVERAGE GLUCOSE (eAG)", "mg/dL", "", "108")]),
    "lft": ("BIOCHEMISTRY", "LIVER FUNCTION TEST", [
        ("BILIRUBIN - TOTAL", "mg/dL", "0.3 - 1.2", "0.7"), ("SGPT (ALT)", "U/L", "< 35", "22"),
        ("SGOT (AST)", "U/L", "< 35", "24"), ("ALKALINE PHOSPHATASE", "U/L", "30 - 120", "78"),
        ("TOTAL PROTEIN", "g/dL", "6.4 - 8.3", "7.2"), ("ALBUMIN", "g/dL", "3.5 - 5.2", "4.4")]),
    "other": ("BIOCHEMISTRY", "ROUTINE CHEMISTRY", [
        ("VITAMIN D, 25-HYDROXY", "ng/mL", "30 - 100", "34.5"), ("SERUM CREATININE", "mg/dL", "0.6 - 1.1", "0.8"),
        ("FASTING GLUCOSE", "mg/dL", "70 - 100", "92"), ("BLOOD UREA", "mg/dL", "15 - 40", "27"),
        ("URIC ACID", "mg/dL", "2.6 - 6.0", "4.1"), ("C-REACTIVE PROTEIN (CRP)", "mg/L", "0 - 5", "2.2")]),
    "wrapped": ("HAEMATOLOGY", "COMPLETE BLOOD COUNT", [
        ("MEAN CORPUSCULAR HEMOGLOBIN CONCENTRATION", "g/dL", "31.5 - 34.5", "32.9"),
        ("RED CELL DISTRIBUTION WIDTH - COEFFICIENT OF VARIATION", "%", "11.6 - 14.0", "12.8")]),
}
PEOPLE = [("Kavita Menon", "F", 34), ("Arjun Deshpande", "M", 41), ("Farhan Qureshi", "M", 29), ("Ananya Iyer", "F", 26),
          ("Rohit Bhandari", "M", 52), ("Sunita Pillai", "F", 47), ("Imran Sheikh", "M", 38), ("Neha Kulkarni", "F", 31),
          ("Gurpreet Sandhu", "M", 45), ("Lakshmi Narayanan", "F", 58)]
ADDR = [["Flat 402, Shanti Residency", "Sector 21, Near City Mall", "Pune, Maharashtra 411038"],
        ["12/B, Lotus Heights, MG Road", "Bengaluru 560001"], ["H.No. 7-1-23, Ameerpet", "Hyderabad - 500016"],
        ["C-14, Green Park Extension", "New Delhi 110016"], ["Door No 5, 3rd Cross, Indiranagar", "Chennai 600020"]]
DOCS_ = ["Dr. S. Rangarajan", "Dr. Meera Joshi", "Dr. A. Khanna", "Dr. P. Banerjee"]
LAB = "Sample Diagnostics (synthetic)"


class Doc:
    def __init__(self, doc_id: str, person: int, desc: str, tags: list[str], header=None, footer=None):
        self.id, self.desc, self.tags = doc_id, desc, tags
        self.name, self.sex, self.age = PEOPLE[person % len(PEOPLE)]
        self.addr = ADDR[person % len(ADDR)]
        self.doctor = DOCS_[person % len(DOCS_)]
        self.date = f"{RNG.randint(1, 28):02d}/{RNG.randint(1, 12):02d}/2026"
        self.mobile = f"9{RNG.randint(1000, 9999)} {RNG.randint(10000, 99999)}"
        self.uhid = f"UH{RNG.randint(1000000, 9999999)}"
        self.path = OUT / f"{doc_id}.pdf"
        self.c = canvas.Canvas(str(self.path), pagesize=A4)
        self.pii: list[dict] = []
        self.rows: list[dict] = []
        self.header, self.footer = header, footer
        self.pg, self.y = 0, 0.0
        self.page_break()

    def page_break(self, first=False):
        if self.pg:
            if self.footer:
                self.footer(self)
            self.c.showPage()
        self.pg += 1
        self.y = 800
        self.text(f"{LAB}  -  Page {self.pg}", size=9, font="Helvetica-Bold")
        if self.header:
            self.header(self)

    def text(self, s, x=40, size=10, font="Helvetica", pii=(), dy=15):
        if self.y < 90:
            self.page_break()
        self.c.setFont(font, size)
        self.c.drawString(x, self.y, s)
        for needle, typ in pii:
            self.pii.append({"type": typ, "needle": needle, "page": self.pg})
        self.y -= dy

    def gap(self, h=10):
        self.y -= h

    def columns(self):
        for x, s in ((40, "TEST"), (275, "VALUE"), (335, "UNIT"), (430, "REFERENCE")):
            self.c.setFont("Helvetica-Bold", 9)
            self.c.drawString(x, self.y, s)
        self.y -= 14

    def panel(self, key: str, flag_first=True, show_titles=True):
        dept, title, rows = PANELS[key]
        if show_titles:
            self.text(dept, font="Helvetica-Bold", size=11)
            self.text(title, font="Helvetica-Bold", size=11)
        self.columns()
        for i, (name, unit, ref, val) in enumerate(rows):
            self.row(name, val, unit, ref, flag="L" if (i == 0 and flag_first and key == "cbc") else "")

    def row(self, name, val, unit, ref, flag=""):
        if self.y < 90:
            self.page_break()
            self.columns()
        self.c.setFont("Helvetica", 10)
        wrapped = len(name) > 34
        if wrapped:
            cut = name.rfind(" ", 0, 34)
            self.c.drawString(40, self.y, name[:cut])
            self.y -= 12
            self.c.drawString(40, self.y, name[cut + 1:])
        else:
            self.c.drawString(40, self.y, name)
        if flag:
            self.c.drawString(255, self.y, flag)
        self.c.drawString(275, self.y, val)
        self.c.drawString(335, self.y, unit)
        self.c.drawString(430, self.y, ref)
        self.rows.append({"name": name, "value": val, "unit": unit, "page": self.pg})
        self.y -= 15

    def person_block(self, labels=True, phone=True, email=True, addr=True, ids=True):
        n = f"Ms. {self.name}" if self.sex == "F" else f"Mr. {self.name}"
        self.text(f"Patient Name : {n}" if labels else n, pii=[(self.name, "name")])
        self.text(f"Age / Sex : {self.age} YRS / {self.sex}")
        if ids:
            self.text(f"UHID : {self.uhid}", pii=[(self.uhid, "id")])
        self.text(f"Referred by : {self.doctor} (MD)", pii=[(self.doctor, "doctor")])
        if phone:
            self.text(f"Mobile : +91 {self.mobile}", pii=[(self.mobile, "phone")])
        if email:
            em = self.name.lower().replace(" ", ".") + "@mailbox.example"
            self.text(f"Email : {em}", pii=[(em, "email")])
        if addr:
            for i, ln in enumerate(self.addr):
                self.text(("Address : " if i == 0 else "          ") + ln, pii=[(ln, "address")])
        self.text(f"Reported on : {self.date} 01:52 PM")

    def fields(self):
        return {"age": str(self.age), "sex": self.sex, "report_date": self.date}

    def close(self):
        if self.footer:
            self.footer(self)
        self.c.showPage()
        self.c.save()
        return {"id": self.id, "kind": "pdf", "files": [self.path.name], "desc": self.desc, "tags": self.tags,
                "pii": self.pii, "rows": self.rows, "fields": self.fields(), "pages": self.pg}


def find_bbox(page, needle: str):
    """Bounding box (points, top-left origin) of the consecutive words that spell `needle`."""
    toks = needle.split()
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    for i in range(len(words) - len(toks) + 1):
        if all(words[i + k]["text"].strip(",") == toks[k].strip(",") for k in range(len(toks))):
            ws = words[i:i + len(toks)]
            return [min(w["x0"] for w in ws), min(w["top"] for w in ws), max(w["x1"] for w in ws), max(w["bottom"] for w in ws)]
    return None


def build_pdfs() -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    docs = []

    # --- normal cases -------------------------------------------------------
    d = Doc("N01", 0, "Standard layout: full patient block above one table", ["normal", "header"])
    d.text("Phone: 020 4123 9876   hello@labmail.example", size=9); d.gap(); d.person_block(); d.gap(); d.panel("cbc"); docs.append(d.close())
    d = Doc("N02", 1, "Lipid profile, UHID and +91 mobile in header", ["normal", "header"])
    d.person_block(email=False); d.gap(); d.panel("lipid"); docs.append(d.close())
    d = Doc("N03", 2, "Two panels back to back, header block", ["normal", "header", "two_panels"])
    d.person_block(addr=False); d.gap(); d.panel("hba1c"); d.gap(); d.panel("thyroid"); docs.append(d.close())
    d = Doc("N04", 3, "Minimal header: name and age only", ["normal", "header", "minimal"])
    d.text(f"Name: {d.name}", pii=[(d.name, "name")]); d.text(f"Age / Sex : {d.age} YRS / {d.sex}"); d.text(f"Collected on : {d.date}")
    d.gap(); d.panel("lft"); docs.append(d.close())

    # --- PII in awkward places ---------------------------------------------
    def footer_contact(d):
        d.c.setFont("Helvetica", 8)
        d.c.drawString(40, 60, "Home collection: call 1800 123 4567 / " + d.mobile)
        d.c.drawString(40, 50, "Patient address on file: " + ", ".join(d.addr))
    d = Doc("P01", 4, "PII only in the footer under the table", ["placement", "footer"])
    d.text(f"Age / Sex : {d.age} YRS / {d.sex}"); d.text(f"Reported on : {d.date}"); d.gap(); d.panel("cbc")
    d.pii += [{"type": "phone", "needle": d.mobile, "page": 1}] + [{"type": "address", "needle": a, "page": 1} for a in d.addr]
    footer_contact(d); d.footer = None; docs.append(d.close())

    d = Doc("P02", 5, "PII box between two separate result tables", ["placement", "between_tables"])
    d.text(f"Age / Sex : {d.age} YRS / {d.sex}"); d.text(f"Reported on : {d.date}"); d.gap(); d.panel("cbc"); d.gap(20)
    d.text("PATIENT CONTACT DETAILS", font="Helvetica-Bold")
    d.text(f"Name : {d.name}", pii=[(d.name, "name")]); d.text(f"Mobile : {d.mobile}", pii=[(d.mobile, "phone")])
    for i, ln in enumerate(d.addr):
        d.text(("Address : " if i == 0 else "          ") + ln, pii=[(ln, "address")])
    d.gap(20); d.panel("lipid"); docs.append(d.close())

    def banner(d):
        d.text(f"Patient: {d.name} | {d.age} Y / {d.sex} | {d.uhid}", size=9, pii=[(d.name, "name"), (d.uhid, "id")])
    d = Doc("P03", 6, "Patient banner repeated mid-table (continuation header)", ["placement", "mid_table"])
    d.text(f"Reported on : {d.date}"); d.gap(); d.panel("lft", show_titles=True); banner(d)
    for r in PANELS["lipid"][2]:
        d.row(r[0], r[3], r[1], r[2])
    docs.append(d.close())

    d = Doc("P04", 7, "Side box in the right margin next to the table", ["placement", "side_box"])
    d.text(f"Age / Sex : {d.age} YRS / {d.sex}"); d.text(f"Collected on : {d.date}"); d.gap(); d.panel("cbc")
    d.y = 640
    for s, t in ((f"{d.name}", "name"), (f"M: {d.mobile}", "phone"), (d.addr[0], "address"), (d.addr[-1], "address")):
        d.c.setFont("Helvetica", 7); d.c.drawString(495, d.y, s); d.y -= 11
        d.pii.append({"type": t, "needle": s.replace("M: ", ""), "page": 1})
    docs.append(d.close())

    def run_header(d):
        d.text(f"Patient: {d.name}   Ph: {d.mobile}   Page {d.pg}", size=8, pii=[(d.name, "name"), (d.mobile, "phone")])
    d = Doc("P05", 8, "Multi-page: running patient header on every page, address in last footer", ["placement", "multipage", "footer"], header=run_header)
    d.text(f"Age / Sex : {d.age} YRS / {d.sex}"); d.text(f"Reported on : {d.date}"); d.gap()
    d.panel("cbc"); d.panel("lipid"); d.panel("lft"); d.panel("thyroid"); d.page_break()
    d.panel("hba1c"); d.panel("other")
    d.text("Address: " + ", ".join(d.addr), size=8, pii=[(a, "address") for a in d.addr]); docs.append(d.close())

    d = Doc("P06", 9, "Unlabelled name inside a sentence between panels", ["placement", "free_text", "name_unlabelled"])
    d.text(f"Age / Sex : {d.age} YRS / {d.sex}"); d.text(f"Reported on : {d.date}"); d.gap(); d.panel("hba1c"); d.gap(15)
    d.text(f"Report prepared for {d.name} ({d.age}Y/{d.sex}) on request of the treating physician.", pii=[(d.name, "name")])
    d.gap(15); d.panel("thyroid"); docs.append(d.close())

    d = Doc("P07", 0, "Unlabelled postal address paragraph between tables", ["placement", "free_text", "address_unlabelled"])
    d.text(f"Age / Sex : {d.age} YRS / {d.sex}"); d.text(f"Collected on : {d.date}"); d.gap(); d.panel("lipid"); d.gap(15)
    d.text("Sample collected at residence:", font="Helvetica-Oblique")
    for ln in d.addr:
        d.text(ln, pii=[(ln, "address")])
    d.gap(15); d.panel("hba1c"); docs.append(d.close())

    d = Doc("P08", 1, "Free-text clinical remark with name, doctor and a phone number", ["placement", "free_text", "remarks"])
    d.text(f"Age / Sex : {d.age} YRS / {d.sex}"); d.text(f"Reported on : {d.date}"); d.gap(); d.panel("cbc"); d.gap(10)
    d.text(f"Remarks: {d.name} reports fatigue for two weeks; {d.doctor} advised repeat in 6 weeks.", size=9, pii=[(d.name, "name"), (d.doctor, "doctor")])
    d.text(f"Call {d.mobile} to collect the printed report.", size=9, pii=[(d.mobile, "phone")]); docs.append(d.close())

    d = Doc("P09", 2, "URL, QR text, barcode and sample numbers after the table", ["placement", "tokens"])
    d.text(f"Age / Sex : {d.age} YRS / {d.sex}"); d.text(f"Reported on : {d.date}"); d.gap(); d.panel("thyroid"); d.gap(10)
    d.text("Scan to download: www.samplelabs.example/r/AB12CD34EF", size=9, pii=[("www.samplelabs.example/r/AB12CD34EF", "url")])
    d.text("Barcode 8830012345678   Sample ID SMP-2026-0099817", size=9, pii=[("8830012345678", "id"), ("SMP-2026-0099817", "id")])
    d.text("Follow us @samplelabs_india   Visit https://samplelabs.example/portal", size=9, pii=[("@samplelabs_india", "url"), ("https://samplelabs.example/portal", "url")])
    docs.append(d.close())

    d = Doc("P10", 3, "DOB in the age line; Aadhaar, ABHA and policy numbers in the footer", ["placement", "ids", "dob"])
    d.text(f"Age / DOB : {d.age} Y / 03-04-1992", pii=[("03-04-1992", "dob")]); d.text(f"Sex : {d.sex}"); d.text(f"Reported on : {d.date}")
    d.gap(); d.panel("lft"); d.gap(15)
    d.text("Aadhaar: 4821 7733 0915   ABHA: 91-4417-8820-3356", size=9, pii=[("4821 7733 0915", "id"), ("91-4417-8820-3356", "id")])
    d.text("Insurance policy PLC-77310088   TPA member 55012349", size=9, pii=[("PLC-77310088", "id"), ("55012349", "id")]); docs.append(d.close())

    d = Doc("P11", 4, "Phone number formats zoo (STD, brackets, spaces, +91, 0-prefix, extension)", ["placement", "phone_formats"])
    d.text(f"Age / Sex : {d.age} YRS / {d.sex}"); d.text(f"Reported on : {d.date}"); d.gap(); d.panel("hba1c"); d.gap(10)
    for s, n in (("Tel: (022) 2345 6789", "(022) 2345 6789"), ("Landline 080-4123-9876 ext 14", "080-4123-9876"),
                 ("WhatsApp +91-98765-43210", "98765-43210"), ("Alt: 09812345670", "09812345670"),
                 ("Mob 91 98123 45671", "98123 45671"), ("Contact: 9876501234", "9876501234"), ("Ph: 011 2654 1122", "011 2654 1122")):
        d.text(s, size=9, pii=[(n, "phone")])
    docs.append(d.close())

    d = Doc("P12", 5, "Hindi labels and Devanagari name/address (text layer, unshaped)", ["placement", "hindi"])
    d.text(f"Age / Sex : {d.age} YRS / {d.sex}"); d.text(f"Reported on : {d.date}"); d.gap(); d.panel("cbc"); d.gap(10)
    for s, t, n in (("नाम: कविता मेनन", "name", "कविता मेनन"), ("पता: फ्लैट 402, शांति रेजिडेंसी, पुणे", "address", "फ्लैट 402, शांति रेजिडेंसी, पुणे"),
                    ("मोबाइल: 9876512345", "phone", "9876512345")):
        d.text(s, font="Poppins", size=9, pii=[(n, t)])
    docs.append(d.close())

    d = Doc("P13", 6, "Adversarial: PII hidden inside result rows and a name+age line", ["adversarial", "in_row"])
    d.text(f"Age / Sex : {d.age} YRS / {d.sex}"); d.text(f"Reported on : {d.date}"); d.gap(); d.columns()
    d.row(f"HEMOGLOBIN (patient {d.name})", "13.1", "g/dL", "12.0 - 15.0")
    d.pii.append({"type": "name", "needle": d.name, "page": 1})
    d.row("TOTAL RBC COUNT", "4.35", "10^6/µL", "3.80 - 4.80")
    d.row(f"SERUM CREATININE c/o {d.doctor}", "0.8", "mg/dL", "0.6 - 1.1")
    d.pii.append({"type": "doctor", "needle": d.doctor, "page": 1})
    d.row(f"PLATELET COUNT {d.mobile}", "251", "10^3/µL", "150 - 410")
    d.pii.append({"type": "phone", "needle": d.mobile, "page": 1})
    d.text(f"{d.name}  {d.age} Y  {d.sex}", pii=[(d.name, "name")]); docs.append(d.close())

    def late_pii(d):
        d.c.setFont("Helvetica", 7); d.c.drawString(40, 40, f"Printed for: {d.name}, {d.addr[0]}")
    d = Doc("P14", 7, "Clean letterhead; patient name and address only after the signatures", ["placement", "after_signature"])
    d.text(f"Age / Sex : {d.age} YRS / {d.sex}"); d.text(f"Collected on : {d.date}"); d.gap(); d.panel("lipid"); d.gap(15)
    d.text("Dr. N. Udaharan, MBBS MD Pathologist        T. Sample, DMLT Lab Incharge", size=9); d.text("NOT VALID FOR MEDICO LEGAL PURPOSE", size=8)
    d.pii += [{"type": "name", "needle": d.name, "page": 1}, {"type": "address", "needle": d.addr[0], "page": 1}]
    late_pii(d); docs.append(d.close())

    d = Doc("P15", 8, "Tests outside the known vocabulary (measures retention cost of an allow-list)", ["retention", "unknown_tests"])
    d.person_block(email=False); d.gap(); d.panel("other"); docs.append(d.close())

    d = Doc("P16", 9, "Long test names that wrap onto two lines", ["retention", "wrapped_rows"])
    d.person_block(email=False, addr=False); d.gap(); d.panel("wrapped"); docs.append(d.close())
    return docs


def to_images(docs: list[dict]) -> list[dict]:
    """Rasterise some PDFs with scan-like damage; bounding boxes of the planted PII follow the transform."""
    specs = [("I01", "N01", 150, 0.0, 0.0, 0, False), ("I02", "P02", 150, 1.6, 0.9, 70, False),
             ("I03", "P04", 150, -1.2, 0.0, 60, True), ("I04", "P01", 120, 0.0, 0.7, 50, True),
             ("I05", "P07", 130, 2.2, 0.6, 55, False), ("I06", "P05", 130, 0.8, 0.5, 65, False),
             ("I07", "P03", 150, 0.0, 0.0, 0, False)]
    by_id = {d["id"]: d for d in docs}
    out = []
    for iid, src, dpi, rot, blur, jpeg, noise in specs:
        d = by_id[src]
        pdf_path = OUT / d["files"][0]
        pdf = pdfium.PdfDocument(str(pdf_path))
        files, pii = [], []
        with pdfplumber.open(pdf_path) as plumber:
            for pi in range(len(pdf)):
                scale = dpi / 72
                im = pdf[pi].render(scale=scale).to_pil().convert("RGB")
                if noise:
                    arr = np.asarray(im).astype(np.int16) + np.random.default_rng(7 + pi).normal(0, 9, (im.height, im.width, 1)).astype(np.int16)
                    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
                if blur:
                    im = im.filter(ImageFilter.GaussianBlur(blur))
                w, h = im.size
                if rot:
                    im = im.rotate(rot, resample=Image.BICUBIC, fillcolor=(255, 255, 255))
                if jpeg:
                    buf = io.BytesIO(); im.save(buf, "JPEG", quality=jpeg); im = Image.open(buf).convert("RGB")
                fname = f"{iid}_p{pi + 1}.png"
                im.save(OUT / fname)
                files.append(fname)
                th = math.radians(rot)
                for item in d["pii"]:
                    if item["page"] != pi + 1:
                        continue
                    bb = find_bbox(plumber.pages[pi], item["needle"])
                    if bb is None:
                        raise SystemExit(f"bbox not found: {src} {item['needle']!r}")
                    x0, y0, x1, y1 = (v * scale for v in bb)
                    cx, cy = w / 2, h / 2
                    pts = []
                    for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                        dx, dy = px - cx, py - cy
                        pts.append((cx + dx * math.cos(th) + dy * math.sin(th), cy - dx * math.sin(th) + dy * math.cos(th)))
                    pii.append({**item, "page": pi + 1, "bbox": [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]})
        out.append({"id": iid, "kind": "image", "files": files, "desc": f"{d['desc']} | scan: dpi={dpi} rot={rot} blur={blur} jpeg={jpeg} noise={noise}",
                    "tags": d["tags"] + ["scan"], "pii": pii, "rows": d["rows"], "fields": d["fields"], "pages": len(files), "source_pdf": src})
    return out


if __name__ == "__main__":
    docs = build_pdfs()
    docs += to_images(docs)
    (OUT / "manifest.json").write_text(json.dumps(docs, indent=1, ensure_ascii=False))
    n_pii = sum(len(d["pii"]) for d in docs)
    print(f"{len(docs)} documents ({sum(d['kind'] == 'pdf' for d in docs)} pdf, {sum(d['kind'] == 'image' for d in docs)} image), {n_pii} planted PII items")
