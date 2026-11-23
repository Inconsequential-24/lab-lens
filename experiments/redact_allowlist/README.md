# Experiment: allow-list redaction ("what is allowed to go?")

A separate experiment. **Nothing here is wired into the LabLens pipeline.** It reads
`reference/panels.yaml` (test names) read-only, and `evaluate.py` imports the current
`lablens.redact` only to compare against it.

## The idea

The current `redact_pii` is a deny-list: it hides what it recognises (the header block before the
first test row, `Name:`-style labels, phone/email/ID patterns, the top 22% of a scan). Anything it
does not recognise reaches the LLM: an address under the table, a contact box between two tables, a
side box in the margin, a name in a free-text remark.

`redact_allowlist.py` flips it. Only three kinds of content may leave:

1. **Result rows**, rebuilt from parsed parts (test name, flag, value, unit, range). A row needs a
   test name followed by a numeric value and a known unit. A PII-looking tail after a known name
   (`HEMOGLOBIN (patient …)`, `PLATELET COUNT 98339 93319`, `… c/o Dr. X`) is cut.
2. **Age, sex and the report date**, parsed out and re-emitted as `Age: 34 YRS` / `Sex: F` /
   `Report date: 17/09/2026`. The line they came from is never copied, so a name on the same line
   cannot ride along. Dates labelled DOB / birth are never used.
3. **Section titles and column headers** from a fixed vocabulary.

Everything else is dropped by default. A **validator** then re-scans every outgoing line (long digit
runs, email, URL/handle, ID tokens, honorifics, PII labels, non-Latin script) and drops any hit.

**Scans:** OCR → group boxes into deskewed visual lines → the same classifier → the allowed boxes
are **copied onto a blank page** (polygon masks). Text that OCR never detected is never copied, so
an OCR miss cannot become a leak (unlike black boxes over detected PII).

`mode="strict"` keeps only test names in the vocabulary (unknown tests are dropped);
`mode="lenient"` (default) also keeps unknown tests when the row structure is present.

## Files

| File | What |
|---|---|
| `generate_dataset.py` | 20 synthetic PDFs + 7 scan-style images, 114 planted PII items, manifest with planted items and expected rows/fields |
| `redact_allowlist.py` | The allow-list redactor (text and image paths) |
| `evaluate.py` | Baseline vs allow-list: leaks, row retention, fields; writes `results/` |
| `test_redact_allowlist.py` | 11 unit tests for the edge cases found while building it |

Run: `python experiments/redact_allowlist/generate_dataset.py && python experiments/redact_allowlist/evaluate.py`
and `python -m pytest experiments/redact_allowlist -q`.

## The dataset (all synthetic, invented names/phones/addresses)

Normal: standard header block (N01–N04). Placement edge cases: footer only (P01), **contact box
between two result tables (P02)**, patient banner repeated mid-table (P03), side box in the right
margin (P04), multi-page running header + last-page address (P05), unlabelled name in a sentence
(P06), unlabelled address paragraph between tables (P07), free-text remark with name/doctor/phone
(P08), URL/QR/barcode/sample IDs (P09), DOB in the age line + Aadhaar/ABHA/policy numbers (P10),
phone-format zoo (P11), Hindi labels and Devanagari name/address (P12), PII inside result rows (P13),
PII after the signatures (P14), tests outside the vocabulary (P15), wrapped two-line test names (P16).
Scans I01–I07 are renders of N01/P02/P04/P01/P07/P05/P03 with rotation (up to 2.2°), blur, noise and JPEG.

## Results (`results/results.md`; 95% Wilson intervals)

**Text PDFs** (the pypdf text layer, as the pipeline reads it):

| | Current `redact_pii` | Allow-list | Allow-list strict |
|---|---|---|---|
| Planted PII items leaked | 20/83 (24%) | **0/83** (CI 0–4%) | 0/83 |
| Documents with any leak | 10/20 | **0/20** | 0/20 |
| Result rows kept | 144/156 (92%) | **156/156** | 141/156 (drops unknown tests) |
| Rows mislabelled | n/a | 0 | 0 |
| Age / sex / report date kept | 19 / 19 / **0** of 20 | 20 / 20 / 20 | 20 / 20 / 20 |

The current redactor leaked names, phones, addresses, IDs, a DOB and a URL whenever they were not in
the header block; it also masks the report date (it sits in the header).

**Scans:**

| | Current `redact_pii` | Allow-list | Allow-list strict |
|---|---|---|---|
| PII items still legible (pixel check) | 9/31 (29%) | **0/31** (CI 0–11%) | 0/31 |
| Rows kept / rows OCR can read in the original | 57/88 (65%) | **85/88 (97%)** | 79/88 |
| Age / sex / report date | 0 / 0 / 1 of 7 | 6 / 6 / 7 | 6 / 6 / 7 |

The one missing age/sex (I07) is a banner line where age shares an OCR box with the patient's name;
the box is dropped rather than risk the name.

## Limitations (read before quoting the numbers)

- **The same person built the dataset and the redactor, and four bugs were fixed while looking at
  this dataset** (validator blocking ranges, MCHC being cut to MCH, a column header glued onto a row,
  a test named like its panel). So 0/83 is a score on a set it was tuned on. The next step is a
  held-out set written by someone else, ideally with real lab layouts (de-identified or recreated).
- Leak check is exact substring on normalised text, plus a first-name/surname token check. It does
  not catch paraphrased or partial PII beyond that.
- Text-path leaks are counted only for **planted** items; lab letterhead phones/emails were not
  counted (the allow-list drops them anyway).
- Scans: the pixel check looks at the planted items' boxes; OCR quality limits row retention.
- `lenient` keeps unknown test names with no PII patterns. A patient name typed into a test-name
  cell with no marker (no honorific, digits or label) would pass. `strict` closes that and costs
  unknown tests (P15).
- What the model loses: free-text notes, method lines and lab remarks are dropped. A clinically
  useful remark ("haemolysed sample") would not reach the LLM. An allow-listed remark vocabulary
  would be the fix.
