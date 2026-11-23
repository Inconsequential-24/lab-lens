"""Score the current redact_pii (baseline) against the allow-list redactor on the planted-PII dataset.

Text PDFs: the pypdf text layer, built exactly as lablens.input_guard builds it.
Images:    pixel leak (ink left inside each planted item's box), OCR leak (OCR of the output finds it),
           row retention against what OCR can read from the unredacted image (the ceiling).
Run: python experiments/redact_allowlist/evaluate.py
"""
from __future__ import annotations

import io
import json
import math
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pypdf
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import redact_allowlist as A  # noqa: E402

sys.path.insert(0, str(REPO / "src"))
from lablens import redact as B  # noqa: E402  (baseline, read-only comparison)

DATA, OUT = HERE / "dataset", HERE / "results"
OUT.mkdir(exist_ok=True)
(OUT / "images").mkdir(exist_ok=True)


def norm(s: str) -> str:
    return re.sub(r"[^0-9a-zऀ-ॿ]+", "", s.lower())


def wilson(k: int, n: int, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0, c - h), 3), round(min(1, c + h), 3))


def leaked(out: str, item: dict) -> bool:
    return norm(item["needle"]) in norm(out)


def partial_name(out: str, item: dict) -> bool:
    if item["type"] not in ("name", "doctor"):
        return False
    toks = [t for t in re.findall(r"[A-Za-zऀ-ॿ]{4,}", item["needle"])]
    return any(re.search(rf"(?<![A-Za-z]){re.escape(t)}(?![A-Za-z])", out, re.I) for t in toks)


def row_kept(out_lines: list[str], row: dict) -> bool:
    """Row on one line, or (baseline keeps pypdf's layout) the name line followed within 3 lines by the value."""
    first = norm(row["name"].split()[0])
    for k, ln in enumerate(out_lines):
        if first and first in norm(ln):
            if row["value"] in ln.split():
                return True
            if any(row["value"] == x.strip() for x in out_lines[k + 1:k + 4]):
                return True
    return False


def row_line(out_lines: list[str], row: dict) -> str | None:
    first = norm(row["name"].split()[0])
    for ln in out_lines:  # prefer the line that starts with the test's own name
        if first and norm(ln).startswith(first) and row["value"] in ln.split():
            return ln
    for ln in out_lines:
        if first and first in norm(ln) and row["value"] in ln.split():
            return ln
    return None


def mislabelled(out_lines: list[str], row: dict) -> bool:
    """Kept row whose line does not start with the expected test name (e.g. a header glued in front)."""
    ln = row_line(out_lines, row)
    return bool(ln) and not norm(ln).startswith(norm(row["name"].split()[0]))


def fields_kept(out: str, f: dict) -> dict:
    lines = out.split("\n")
    age = any(re.search(r"\bage\b", ln, re.I) and re.search(rf"(?<!\d){f['age']}(?!\d)", ln) for ln in lines)
    sex = any(re.search(r"\b(sex|gender)\b", ln, re.I) and re.search(rf"\b{f['sex']}\b", ln) for ln in lines)
    return {"age": age, "sex": sex, "report_date": f["report_date"] in out}


def text_layer(path: Path) -> str:
    pages = [p.extract_text() or "" for p in pypdf.PdfReader(path).pages]
    return "\n".join(f"[page {i}]\n{t}" for i, t in enumerate(pages, 1))


def known(name: str) -> bool:
    return A.clean_name(name, "strict") is not None


METHODS_TEXT = {
    "baseline": lambda data, t: B.redact_pii(data, "pdf", t).text,
    "allowlist": lambda data, t: A.redact_text(t, "lenient").text,
    "allowlist_strict": lambda data, t: A.redact_text(t, "strict").text,
}


def score_text(docs):
    per_doc, agg = [], defaultdict(lambda: defaultdict(int))
    for d in docs:
        path = DATA / d["files"][0]
        data, t = path.read_bytes(), text_layer(path)
        for m, fn in METHODS_TEXT.items():
            t0 = time.perf_counter()
            out = fn(data, t)
            ms = (time.perf_counter() - t0) * 1000
            (OUT / f"{d['id']}.{m}.txt").write_text(out)
            lines = out.split("\n")
            leaks = [i for i in d["pii"] if leaked(out, i)]
            parts = [i for i in d["pii"] if not leaked(out, i) and partial_name(out, i)]
            kept = [r for r in d["rows"] if row_kept(lines, r)]
            fk = fields_kept(out, d["fields"])
            a = agg[m]
            a["pii"] += len(d["pii"]); a["leaks"] += len(leaks); a["partial"] += len(parts)
            a["docs"] += 1; a["docs_leaky"] += bool(leaks); a["rows"] += len(d["rows"]); a["rows_kept"] += len(kept)
            a["rows_known"] += sum(known(r["name"]) for r in d["rows"])
            a["rows_known_kept"] += sum(known(r["name"]) for r in kept)
            a["ms"] += ms
            if m != "baseline":
                a["mislabelled"] += sum(mislabelled(lines, r) for r in kept)
            for k, v in fk.items():
                a[f"field_{k}"] += v
            for i in d["pii"]:
                a[f"type_{i['type']}_n"] += 1
                a[f"type_{i['type']}_leak"] += leaked(out, i)
            per_doc.append({"id": d["id"], "method": m, "tags": d["tags"], "pii": len(d["pii"]),
                            "leaked": [f"{i['type']}" for i in leaks], "partial_name": len(parts),
                            "rows": len(d["rows"]), "rows_kept": len(kept), "fields": fk})
    return per_doc, agg


def _crop(im: Image.Image, bb):
    x0, y0, x1, y1 = (int(round(v)) for v in bb)
    return np.asarray(im.convert("L").crop((max(0, x0 - 1), max(0, y0 - 1), x1 + 1, y1 + 1))).astype(int)


def pixel_leak(src: Image.Image, out: Image.Image, bb) -> bool:
    """Text stays legible when its dark strokes AND the light background around them both survive.
    A black box kills the background, a white page kills the strokes; either one hides the text."""
    a, b = _crop(src, bb), _crop(out, bb)
    ink_px, bg_px = a < 128, a >= 200
    if ink_px.sum() == 0:
        return False
    ink_kept = (b[ink_px] < 128).mean()
    bg_kept = (b[bg_px] >= 200).mean() if bg_px.sum() else 0.0
    return bool(ink_kept >= 0.5 and bg_kept >= 0.5)


def ocr_text(im) -> str:
    return "\n".join(" ".join(t for t, _ in ln) for ln in A.visual_lines(A.ocr_boxes(im)))


def score_images(docs):
    per_doc, agg = [], defaultdict(lambda: defaultdict(int))
    for d in docs:
        pages = [Image.open(DATA / f).convert("RGB") for f in d["files"]]
        ceiling_txt = "\n".join(ocr_text(p) for p in pages)
        ceiling_rows = [r for r in d["rows"] if row_kept(ceiling_txt.split("\n"), r)]
        ceiling_pii = [i for i in d["pii"] if leaked(ceiling_txt, i)]
        for m in ("baseline", "allowlist", "allowlist_strict"):
            outs, t0 = [], time.perf_counter()
            for p in pages:
                if m == "baseline":
                    outs.append(B.redact_image(p, True)[0])
                else:
                    outs.append(A.redact_image(p, "lenient" if m == "allowlist" else "strict")[0])
            ms = (time.perf_counter() - t0) * 1000
            for k, o in enumerate(outs, 1):
                o.save(OUT / "images" / f"{d['id']}_p{k}.{m}.png")
            out_txt = "\n".join(ocr_text(o) for o in outs)
            px = [i for i in d["pii"] if pixel_leak(pages[i["page"] - 1], outs[i["page"] - 1], i["bbox"])]
            ocr = [i for i in d["pii"] if leaked(out_txt, i)]
            kept = [r for r in ceiling_rows if row_kept(out_txt.split("\n"), r)]
            fk = fields_kept(out_txt, d["fields"])
            a = agg[m]
            a["pii"] += len(d["pii"]); a["pixel_leaks"] += len(px); a["ocr_leaks"] += len(ocr)
            a["ocr_readable_pii"] += len(ceiling_pii)
            a["docs"] += 1; a["docs_leaky"] += bool(px)
            a["rows_ceiling"] += len(ceiling_rows); a["rows_kept"] += len(kept); a["rows"] += len(d["rows"])
            a["ms"] += ms
            for k, v in fk.items():
                a[f"field_{k}"] += v
            per_doc.append({"id": d["id"], "method": m, "pii": len(d["pii"]), "pixel_leaked": [i["type"] for i in px],
                            "ocr_leaked": [i["type"] for i in ocr], "rows_ceiling": len(ceiling_rows), "rows_kept": len(kept), "fields": fk})
    return per_doc, agg


def pct(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({(k / n * 100 if n else 0):.1f}%, CI {lo:.2f}–{hi:.2f})"


def main():
    docs = json.loads((DATA / "manifest.json").read_text())
    tdocs = [d for d in docs if d["kind"] == "pdf"]
    idocs = [d for d in docs if d["kind"] == "image"]
    tp, ta = score_text(tdocs)
    ip, ia = score_images(idocs)
    md = ["# Allow-list redaction experiment: results", "",
          f"Dataset: {len(tdocs)} text PDFs and {len(idocs)} scan-style images, synthetic, "
          f"{sum(len(d['pii']) for d in docs)} planted PII items. Intervals are 95% Wilson.", "",
          "## Text PDFs (pypdf text layer, as the pipeline reads it)", "",
          "| Method | PII items leaked | Docs with any leak | Name/doctor partial leaks | Rows kept | Known-test rows kept | Rows mislabelled | Age kept | Sex kept | Report date kept | ms/doc |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m, a in ta.items():
        mis = "n/a (keeps layout)" if m == "baseline" else str(a["mislabelled"])
        md.append(f"| {m} | {pct(a['leaks'], a['pii'])} | {a['docs_leaky']}/{a['docs']} | {a['partial']} | {pct(a['rows_kept'], a['rows'])} | "
                  f"{pct(a['rows_known_kept'], a['rows_known'])} | {mis} | {a['field_age']}/{a['docs']} | {a['field_sex']}/{a['docs']} | "
                  f"{a['field_report_date']}/{a['docs']} | {a['ms'] / a['docs']:.1f} |")
    types = sorted({k[5:-2] for k in ta["baseline"] if k.startswith("type_") and k.endswith("_n")})
    md += ["", "### Leaks by PII type (text PDFs)", "", "| Type | " + " | ".join(ta) + " |", "|---|" + "---|" * len(ta)]
    for t in types:
        md.append(f"| {t} | " + " | ".join(f"{a[f'type_{t}_leak']}/{a[f'type_{t}_n']}" for a in ta.values()) + " |")
    md += ["", "### Per document (text PDFs): leaked PII types", "", "| Doc | Case | " + " | ".join(ta) + " | Rows kept (allowlist) |", "|---|---|" + "---|" * (len(ta) + 1)]
    desc = {d["id"]: d["desc"] for d in docs}
    for d in tdocs:
        cells = []
        for m in ta:
            r = next(x for x in tp if x["id"] == d["id"] and x["method"] == m)
            cells.append(", ".join(r["leaked"]) or "none")
        r = next(x for x in tp if x["id"] == d["id"] and x["method"] == "allowlist")
        md.append(f"| {d['id']} | {desc[d['id']]} | " + " | ".join(cells) + f" | {r['rows_kept']}/{r['rows']} |")
    md += ["", "## Scan-style images", "",
           "| Method | PII items with ink left (pixel leak) | OCR can read it back | Docs with any pixel leak | Rows kept / OCR-readable rows | Age | Sex | Report date | ms/doc |",
           "|---|---|---|---|---|---|---|---|---|"]
    for m, a in ia.items():
        md.append(f"| {m} | {pct(a['pixel_leaks'], a['pii'])} | {a['ocr_leaks']}/{a['ocr_readable_pii']} readable | {a['docs_leaky']}/{a['docs']} | "
                  f"{pct(a['rows_kept'], a['rows_ceiling'])} | {a['field_age']}/{a['docs']} | {a['field_sex']}/{a['docs']} | {a['field_report_date']}/{a['docs']} | {a['ms'] / a['docs']:.0f} |")
    md += ["", "| Image | " + " | ".join(ia) + " |", "|---|" + "---|" * len(ia)]
    for d in idocs:
        md.append(f"| {d['id']} ({d.get('source_pdf')}) | " + " | ".join(
            ", ".join(next(x for x in ip if x["id"] == d["id"] and x["method"] == m)["pixel_leaked"]) or "none" for m in ia) + " |")
    (OUT / "results.md").write_text("\n".join(md) + "\n")
    (OUT / "results.json").write_text(json.dumps({"text": {"per_doc": tp, "agg": ta}, "images": {"per_doc": ip, "agg": ia}}, indent=1, default=dict))
    print("\n".join(md))


if __name__ == "__main__":
    main()
