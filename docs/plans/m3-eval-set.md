# Milestone 3 change: 15 source reports, 30 derived eval cases

Status: APPROVED (2026-11-21, by user)

## Goal
Show the eval set is not duplicated training data: 15 synthetic **source** reports, and 30
**eval cases** each derived from one source by a recorded, controlled change.

## Requirements
- FR-01: 15 source reports (current D01-D15, clean digital PDFs, 3 per panel). Used for
  development and tuning only; never scored in the reported numbers.
- FR-02: 30 eval cases (E01-E30), each with `source: Dxx` and `variation: <type>` plus the
  exact change applied. Mix:
  - 10 controlled variations: values, age or sex changed so flags, severity or next step
    differ from the source.
  - 8 perturbations: scanned image (rotation, blur, noise, JPEG), multi-page, layout change.
  - 6 extraction challenges: abbreviated names, unit changes (T3 ng/dL), `<0.010` style
    values, missing ranges, unit-less ratio rows.
  - 6 adversarial: critical values (incl. one in a blurry image), wrong printed flag,
    injected instruction, condition-naming table, unsupported test with a lab remark.
  - Current T01-T15 are re-mapped into these groups (each gets a `source`), and 15 new
    cases are added.
- FR-03: Every source is used by at least one eval case; no source by more than 3.
- FR-04: Anti-duplication check in the generator, which refuses to write data if any eval
  case has the same file SHA-256, or the same values + layout + rendering, as its source
  or another case.
- FR-05: All 30 eval cases are frozen (expected outcomes committed) before any tuning.
  Tuning uses the 15 sources only.
- FR-06: Results are reported overall and per variation group.
- FR-07: `data/README.md` and PLAN.md sections 1, 5, 7, 8, 12 and 13 updated to match.

## Trade-offs
- Eval cases share layouts and panels with the tuned sources. That is deliberate (it shows
  how the system copes when a known report changes), but it is not a test on unseen report
  formats. The variation that changes layout and the anti-duplication check limit this, and
  the README says so.
- Cost: the frozen set grows from 15 to 30 cases, so 3 runs is 90 instead of 45 report runs.
  At section 8's ~₹0.6 per run, that is about ₹27 more, which still fits within the ₹500 budget (section 8 updated).

## Tasks
| # | Task | Files | Location |
|---|---|---|---|
| 1 | Restructure cases: D01-D15 become sources; E01-E30 with `source`/`variation` | `data/case_specs.yaml` | Verified |
| 2 | Generator: apply a variation on top of a source; anti-duplication check | `scripts/generate_reports.py` | Verified (internals to investigate) |
| 3 | Tests for the source/variation linkage and the duplicate check | `tests/test_generator.py` | Verified |
| 4 | Regenerate reports and ground truth | `data/reports/`, `data/ground_truth/` | Verified |
| 5 | Update docs | `data/README.md`, `PLAN.md` | Verified |

## Acceptance
- `pytest tests/` passes, including a test that fails if an eval case duplicates a source.
- `index.json` lists 15 sources and 30 eval cases, each case naming its source and variation.
