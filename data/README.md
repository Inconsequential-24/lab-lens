# Synthetic lab reports

15 synthetic **source** reports and 30 **eval cases** derived from them, all with exact
ground truth. The sources are used for development and tuning only. The 30 eval cases are
frozen before tuning and are the only cases scored in the reported numbers.

All 30 evaluation reports are synthetic. Real lab reports were used only as format
references for layouts and were not copied into the repository or into any evaluation. No
real patient data is stored in this repository.

**Every report is fictional.** Lab names, people, IDs, addresses, phone numbers and signatures
are invented, and every page carries the line "SYNTHETIC TEST REPORT - generated for software
evaluation - not a real patient".

## Regenerate

```sh
pip install -r requirements-data.txt
python scripts/generate_reports.py          # writes data/reports and data/ground_truth
python -m pytest tests/test_generator.py    # 32 checks, including byte-for-byte determinism
```

The run is deterministic for the seed in `data/case_specs.yaml`.

## What is here

| Path | Contents |
|---|---|
| `case_specs.yaml` | The 15 sources and 30 eval cases, written by hand: scenario, layout, key values, expected outcome; each eval case names its `source`, `variation` and `change` |
| `reports/source/D01-D15.pdf` | Sources: clean digital PDFs, 3 per panel, used for tuning only |
| `reports/eval/E01-E30.pdf` | Eval cases, frozen before tuning and scored |
| `reports/eval/*.png` | Scanned-image inputs for E11, E13, E14, E16, E18 and E26 (rotation, blur, noise, JPEG artefacts) |
| `ground_truth/<id>.json` | Every printed test: name, raw value, comparator, units, printed range, page, expected flag, severity, critical status; plus remarks, unsupported tests, the expected next step, and for eval cases the source, variation and change |
| `ground_truth/index.json` | Sources and eval cases, listed separately |

## How eval cases are derived

Each eval case starts from a deep copy of its source's spec and applies only its own fields
on top (values, names, units, printed flags and extra rows merge key by key; other fields
replace the source's). Its expected outcome is always written by hand. There are four
variation groups, and results are reported overall and per group:

| Group | Cases | What changes |
|---|---|---|
| Controlled variation | E01-E10 | Values, age or sex, so that flags, severity or the next step differ from the source |
| Perturbation | E11-E18 | Scanned images, a second panel over several pages, or a different layout for the same values |
| Extraction challenge | E19-E24 | Abbreviated or long printed names, a unit variant, `<0.010` style values, missing ranges |
| Adversarial | E25-E30 | Critical values (one in a blurry image), a wrong printed flag, an injected instruction, a condition-naming table, an unsupported test with a lab remark |

Every source is used by 1 to 3 eval cases. The generator refuses to write anything if:
- a controlled variation leaves the flags, severity and next step the same as its source, or
- an eval case has the same values, layout and rendering as its source or another case, or
  an identical output file (SHA-256).

Eval cases share panels and layouts with the sources by design: they measure how the system
copes when a known kind of report changes. They are not a test on unseen report formats.

## Coverage

- **Panels:** CBC (14 tests), lipid profile (7), HbA1c with eAG (2), thyroid (T3, T4, TSH),
  liver function (11).
- **Layouts:** four styles modelled on the structure of common Indian lab reports (counts are
  eval cases / sources).
  - A (7 / 4): boxed serif layout, bold abnormal values, an HbA1c interpretation table that
    names conditions.
  - B (8 / 3): banner layout with an H/L flag column.
  - C (9 / 3): dense layout with a technology column and one-sided ranges such as `<200`.
  - D (6 / 5): package-style report with a package title, sub-heading rows inside the table
    ("LIVER FUNCTION TEST (LFT), SERUM") with the method in brackets underneath, the lab's
    own ranges (zero-start like `0 - 55`, tight like `<0.30`, labelled like
    `Desirable : 1.5-3.5`), unit-less ratio rows (AST:ALT), bold-only abnormal values, long
    numbered notes that name conditions (hepatitis, NAFLD, cirrhosis, diabetes, hypothyroidism
    and others), a promotional box, and content that flows across pages.
- **Outcomes in the 30 eval cases:** all three next steps (no action 13, doctor consult 10,
  follow-up package 7) and every rule in the PLAN.md decision table: critical (2), marked
  (5), package (7), mild (2), wrong printed flag (1), missing range (2), all normal (11).
- **Edge cases:** abbreviated names (HGB, TLC, HCT), long printed names, T3 printed in ng/dL,
  `<0.010` and `<0.10` values, a missing printed range (twice), a two-panel report whose LFT
  table breaks across a page (the sub-heading is not repeated on page 2), a wrong printed
  flag, an injected instruction, an unsupported test (Vitamin B12), a lab remark, notes that
  name conditions (each such case lists terms the explanation must not use), and six scanned
  images including a blurry critical value.

## Where layout D came from

Layout D was added after a structural survey of 10 real lab reports, done with a script that
printed only format shapes (every digit replaced by 9; no names, IDs or values). It found that
abnormal values are marked by bold type only, ratio rows often have no unit, ranges often start
at zero, every report had a bracketed method line under each panel heading, and long notes
made up 36-51% of the text and named about 25 different conditions. Layout D reproduces those
patterns with invented names, values and wording. No real report, or any text from one, is
in this repository.

## How the ground truth is made

1. Each case's key values are written by hand in `case_specs.yaml`. Other values are sampled
   inside the normal range, and calculated tests (VLDL, Non-HDL, TC/HDL, eAG, indirect
   bilirubin, globulin, A/G ratio) are computed from the measured ones. The differential count
   always adds up to 100.
2. Expected flags and severity compare each value with the range **printed on that report**
   (bounds inclusive). Critical values use the thresholds in `reference/panels.yaml`, in
   canonical units. The next step follows PLAN.md section 4, implemented separately from the
   pipeline in `generate_reports.py`.
3. The generator stops if its computed outcome disagrees with the hand-written expectation
   for any case, so both would have to be wrong in the same way for an error to slip through.
4. A test checks that every value, unit, range and name in the ground truth appears in the
   PDF's text.

## Known limitations

- Reference ranges and critical thresholds in `reference/panels.yaml` are demonstration
  values. They have not been reviewed by a clinician. Bilirubin and ALT/AST critical
  thresholds are marked `source: demo`.
- Red cell indices (MCV, MCH, MCHC) are sampled independently, not calculated from Hb, RBC and
  PCV, so a few combinations would not occur in a real analyser.
- LOINC codes are the common codes for each test and still need checking against loinc.org.
- Reports are English only. A bilingual report was dropped because the PDF library cannot
  shape Devanagari text correctly.
- Image cases are single-page. Single-panel layout D reports fit on one page; only the
  two-panel case (E12) runs to two pages, while real package reports often run to 4-20.

## NidaanKosha

[NidaanKosha-100k](https://huggingface.co/datasets/ekacare/NidaanKosha-100k-V1.0) (Eka Care,
CC-BY-SA-4.0) comes from real, de-identified Indian lab reports. Because the brief requires
synthetic data only, none of its rows are used in these reports.
`scripts/derive_reference_stats.py` reduces it to aggregates (frequent printed names, units,
range formats and value percentiles, each seen at least 50 times) in
`reference/nidaankosha_stats.json`. Those aggregates are meant for checking the reference
ranges and for training data for the test-name normalizer. If you commit that file, keep its
CC-BY-SA-4.0 attribution.
