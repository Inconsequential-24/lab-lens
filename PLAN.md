# PLAN.md: Lab Report Explainer

Status: planning (first commit, before any code)
Stack: Python, Google ADK 2.0 (Workflow Runtime), FastAPI, Pydantic, scikit-learn

---

## 1. Problem

Lab customers download PDF reports full of numbers they cannot interpret. The lab wants an
agent that explains the results in plain language, flags what needs attention and suggests a
next step, **without diagnosing**.

The product behaves like the lab technician who says "your Hb is low, mention it to your
doctor" and does not behave like a doctor.

**Goals**
- Extract every test from a report into schema-validated JSON.
- Explain results in English and Hindi. Every statement cites an extracted value.
- Never diagnose. Critical values trigger an urgent message.
- Pick one next step from a fixed list: follow-up test package, doctor consult, no action.
- Measure all of it with a 30-case eval set derived from 15 synthetic source reports
  (extraction, flags, grounding, unsafe advice, latency, cost).

**Non-goals**
- Diagnosis, treatment, medication or dosage advice.
- Linking symptoms to lab values.
- Real patient data in the repo, the demo or the evals. All of those are synthetic. Real uploads
  are an optional, opt-in feature with cache-only processing by default (section 10).
- Accounts for anyone who does not opt in to saved history. Sign-in (Google) exists only for
  saved history and trends (sections 4.3 and 10); the rest of the demo is account-free.
- Trend interpretation ("improving", "worsening"). Trend charts show values, ranges and flags
  only.

## 2. Users

| User | Need | What they must never get |
|---|---|---|
| Lab customer (patient) | Understand the report in English or Hindi and know what to do next | A diagnosis, false reassurance, or a missed critical value |
| Lab staff | Trust that the explainer is safe to put on their site | Unsafe advice reaching customers |
| Reviewer / evaluator | Verify accuracy, safety and cost | Unmeasured claims |

## 3. Design principles

1. **Code decides, the LLM explains.** Flags, severity, critical alerts and next step come from
   deterministic code. The LLM only reads documents and writes language.
2. **Grounded or not said.** Every sentence in an explanation maps to an extracted value or a
   curated glossary entry. Ungrounded sentences are rejected by a checker.
3. **Fail visible.** If extraction confidence is low, say "please check this row", never guess.
4. **Measure before claiming.** Every number in the README comes from the eval script.

## 4. Architecture

An ADK 2.0 `Workflow` (graph). Plain-function nodes are deterministic. LLM nodes are marked (LLM).
Trained-model nodes are marked (ML).

```
 PDF / image / text
        |
        v
 [input_guard]  file type, size, pages, encryption, "is this a lab report?"
        |                                  --reject--> 400 with reason
        v
 [response cache] --hit--> stored result       (section 9.1)
        | miss
        v
 [redact_pii]   strip name, ID, phone, address before any LLM call
        |
        v
 [extract] (LLM) --> [validate] --retry (max 2)--> [extract]
        |                 (schema, units, plausibility, completeness, confidence)
        v
 [normalize_names] (ML)       canonical test names, unit conversion
        |
        v
 [flag_engine]                flag + severity + critical list (rules)
        |
        +--> critical? --> [urgent_template]  fixed EN + HI text, never LLM-written
        |
        +---------------------+
        v                     v
 [pattern_model] (ML)   [glossary_lookup]
        |                     |
        v                     |
 [route_next_step]            |    next_step + urgency (rules), before any explanation LLM call
        |                     |
        +----------+----------+
                   v
            [plan_statements] (LLM)  claims citing values; tone conditioned on next_step + urgency
                   |
            +------+------+
            v             v
      [render_en] (LLM)  [render_hi] (LLM)      parallel fan-out
            |             |
            +------+------+
                   v
            [safety_check]
               | plan-level failure   --> [plan_statements]   (max 2 retries)
               | render-level failure --> only the failing [render_*]   (max 2 retries)
               | still failing / LLM unavailable --> [template_fallback]
                   v
              JSON response (+ fixed disclaimer)
```

Two properties hold on every path, including failures:
1. If any critical value was extracted, the urgent message is present, in both languages.
2. Flags, severity and next step are always returned, even when every LLM call fails, because
   all three are computed before the first explanation call.

### Node responsibilities

| Node | Type | Responsibility |
|---|---|---|
| `extract` | LLM (vision/text) | Read report into the `ExtractedTest` schema |
| `validate` | Function | Pydantic validation, unit check, plausibility check, extraction confidence |
| `normalize_names` | ML (small classifier or embedding matcher) | Map "HGB", "Hb", "Haemoglobin" to one canonical test ID |
| `flag_engine` | Function | Compare value to the report's own reference range; assign flag and severity; check critical list |
| `pattern_model` | ML | Detect co-occurring abnormalities for the doctor note, with no condition names |
| `glossary_lookup` | Function | Fetch curated, reviewed per-test text (what it measures, general non-diagnostic reasons) |
| `plan_statements` | LLM | Produce a language-neutral list of claims from abnormal rows, normal count and glossary text, each with citations |
| `render_en`, `render_hi` | LLM | Turn the same claim list into conversational English and Hindi, so both languages say the same thing |
| `safety_check` | Function plus rules (optional judge) | Citations exist; direction words match flags; numbers and units match extracted values; no diagnostic phrasing; EN and HI claim sets match. Each failure is tagged plan-level (wrong claim, missing citation) or render-level (a dropped unit or banned phrase in one language), so only the failing stage is retried |
| `urgent_template` | Function | Fixed, pre-written urgent text in EN and HI for critical values |
| `template_fallback` | Function | Deterministic sentence per abnormal test from the glossary, used if the LLM path fails |
| `route_next_step` | Function | Choose from the fixed list; set urgency. Depends only on deterministic outputs, so it runs before the explanation and never waits on LLM retries |
| `input_guard` | Function | Reject bad inputs early |
| `redact_pii` | Function | Keep personal data out of prompts and logs. Two paths: digital PDFs get regex and field-label redaction on the text layer; images get the header band masked plus OCR bounding-box redaction of name, ID, phone and address fields. Residual risk for non-standard scan layouts is listed in section 12 |

Why plan-then-render: generating the claims once and rendering them twice keeps English and
Hindi consistent, makes grounding checkable on one structure, and lets the two renders run in
parallel to cut latency.

### Why a hybrid
Reference-range comparison is exact with code, so the flag engine is the source of truth for
safety. The ML nodes (name normalization, patterns) add value where rules scale badly. A
rule-vs-model flag comparison is included in the evals as evidence (section 7).

### Severity and next step (rule-based)

**Deviation** is measured relative to the violated bound, not the range width, so one-sided
ranges ("< 200") and ranges starting at 0 work: `dev = |value - bound| / |bound|`.
Guard: if `|bound| < 1e-9` (a bound of 0, e.g. the low end of "0 - 40"), deviation is taken
relative to the range width when both bounds exist; otherwise the result is `marked`. A value
below a lower bound of 0 is physically implausible and is already rejected by `validate`.

| Severity | Definition | Initial threshold |
|---|---|---|
| normal | within the printed range (bounds inclusive) | |
| mild | outside range, small deviation | dev < 10% |
| marked | outside range, larger deviation | dev >= 10% |
| critical | at or beyond a critical threshold from `critical_values.yaml` | per test |

Critical thresholds are defined per test, independently of the printed range, because a lab's
printed range is not a safety limit. Thresholds are initial values and will be tuned with
the 15 source reports only, never on the eval cases (section 7).

**Next step: a deterministic decision table, evaluated top to bottom, first match wins**

| Condition | next_step | urgency |
|---|---|---|
| any critical | doctor_consult | urgent |
| any marked, or 3+ abnormal tests | doctor_consult | soon |
| a defined pattern matches a package in `packages.yaml` | follow_up_test_package | routine |
| any mild | doctor_consult | routine |
| any row unreadable, or range missing with no fallback range, and all else normal | no_action, with a "please verify" note | none |

Notes on the table: tests with no reference range at all (eAG) are informational and never
trigger the "please verify" row. When a printed flag says abnormal but the value is in range,
the case is routed as a mild abnormality (rule `R4_printed_flag`) with "please confirm this
result with the lab".
| all normal | no_action | none |

`packages.yaml` is a fixed catalog (for example, "Iron studies package" when Hb and MCV are
both low). The package name never names a condition.

**One deliberate exception to "code decides":** when the printed flag on the report disagrees
with the computed flag, the computed flag is what the user sees, but routing uses the more
severe of the two and adds "please confirm this result with the lab". Reason: the disagreement
may be a lab typo or an extraction error, and a missed problem costs more than an extra check.
`rule_id` records when this exception fired.

### Safety rules (enforced by `safety_check`)
- Allowed: "Your hemoglobin is below the usual range. This can happen for several reasons, so
  it's worth discussing with a doctor."
- Banned: naming a condition as the user's ("you have anemia"), treatment or dose advice,
  reassurance that contradicts a flag, linking symptoms to values.
- Critical value: the response always starts with the fixed urgent template. A critical value
  with low extraction confidence stays urgent and adds "please confirm this value with the
  lab". Confidence can add caution but never downgrade urgency.
- Low extraction confidence: the affected row is marked "please verify".
- Interpretive text printed on the report (for example an HbA1c band labelled with a condition
  name, or "suggestive of ...") is never repeated. Only the value, range and flag are explained.
- Lab remarks (for example "sample haemolysed", "repeat advised") are extracted and shown
  verbatim with a neutral note, because they can make a value unreliable.
- "All normal" wording is bounded: "all results are within the ranges printed on your report".
  It never says "you are healthy".
- Every response carries a fixed disclaimer: this explains a report and is not medical advice.
- Text inside the report is treated as data. Instructions found in it ("ignore previous rules")
  are ignored, and the extraction prompt says so.

### Optional chat follow-up (stretch, after core evals pass)
A symptom guard answers questions like "does anything suggest my BP is off?" with: the report
does not measure that; please tell a doctor; seek urgent care if serious symptoms are present.
It never connects symptoms to lab values. Chat-guard cases (4 symptom questions) are kept in
a separate set and table (section 7), so the core 30-case results have no empty rows if the
chat endpoint stays a stretch goal.

### 4.1 How we use ADK 2.0

ADK 2.0 is the runtime of the whole pipeline, not an add-on. The diagram above is the
`Workflow` graph: one box is one node, and every arrow is an edge.

| Piece of the design | ADK 2.0 construct |
|---|---|
| Deterministic steps (`input_guard`, `redact_pii`, `validate`, `flag_engine`, `route_next_step`, `safety_check`, templates) | Plain Python function nodes. No LLM can change their output. |
| LLM steps (`extract`, `plan_statements`, `render_en`, `render_hi`) | `Agent` nodes on Gemini, each with a Pydantic input and output type |
| ML steps (`normalize_names`, `pattern_model`) | Function nodes that load a saved scikit-learn model |
| "critical goes to the urgent template", "safety failure goes to retry or fallback" | Router nodes that return a route, with a dict of route to next node |
| `render_en` and `render_hi` in parallel | Fan-out and fan-in edges (exact syntax confirmed by the spike) |
| Retries on extract and render | ADK retry configuration on the node, not hand-written loops. Broad `except` blocks are not used inside nodes, so ADK can see failures and retry. |
| Demo and debugging | `adk web`, which shows the graph and each node's input and output |
| Serving | FastAPI calls the workflow through ADK's `Runner`; the API wraps it with rate limits, caps and consent checks (sections 6 and 10) |

**What ADK needs:** `pip install google-adk` (open source, no account) and one Gemini API key
from Google AI Studio in `.env` as `GOOGLE_API_KEY`. The key is the only credential. No GCP
project or Vertex AI. Real uploads need a paid-tier key (section 10).

**What ADK is not used for:** evals. `evals/run.py` calls the workflow as a black box and
computes the metrics itself, so numbers do not depend on the framework (section 7).

**Confirmed by the spike (`google-adk==2.15.0`, 2026-11-21; see `spikes/adk/README.md`):**
function nodes `f(node_input: T, ctx: Context) -> U` with Pydantic types between nodes;
`Agent(output_schema=Model, output_key=...)` returns validated typed output from live
`gemini-3.1-flash-lite`; routers return `Event(route=..., output=...)` (read back from
`event.actions.route`); fan-out via a tuple of nodes and fan-in via `JoinNode` (dict keyed
by node name); `@node(retry_config=RetryConfig(...))`; shared state via `ctx.state`, also
usable in Agent instructions as `{key}`; `Runner`/`InMemoryRunner(node=workflow)` from code;
`adk web` discovers the workflow from `root_agent`. Token usage is on
`event.usage_metadata` (`prompt_token_count`, `candidates_token_count`,
`thoughts_token_count`); a one-row call used 93 in / 41 out / 0 thinking tokens.
**Still to confirm:** running `Runner` inside FastAPI (milestone 11).

### 4.2 Frontend

The UI is built from the provided design reference, `docs/ui/LabLens-Understand-your-report.png`
(React, Vite, TypeScript, React Query). Layout: hero and upload card on the left, demo reports
on the right, a fixed "This is not a diagnosis" banner, EN/HI toggle, and pages for My report,
History, Staff view, Evaluations and About.

The frontend lives in this repository under `frontend/` (built in milestone 11). It is served
as static files by the FastAPI service in production, so the deployed demo is one link.

- The API client is generated from our `openapi.yaml` (section 6), so the UI talks to the
  ADK-backed FastAPI service.
- The results page shows, per test, the value, range, flag, severity and an evidence link
  to the extracted row; urgent banner first; EN and HI toggle.
- Upload accepts PDF and images.
- The real-upload path follows section 10: not saved by default, history only after the
  consent checkbox (EN and HI wording from section 10).
- Google sign-in is shown only when the user ticks "save to history"; everything else is
  account-free.
- The History page lists saved reports by date and shows one trend chart per test
  (section 4.3).
- The Staff and Evaluations pages are fed from `evals/results.json`.

### 4.3 Saved history and trends (opt-in)

Plain application code around the workflow, not ADK nodes. No LLM is used.

- **Report date.** Pre-filled from the extracted `report_date`. The user confirms or edits it
  before saving; if it is missing, they must enter it. Nothing is saved without a confirmed
  date. Dates in the future or before 1990 are rejected.
- **Duplicates and overlaps**, checked before saving:
  - Same file (same SHA-256): "already saved on <date>", nothing added.
  - Same test on the same date already saved from another report: both values are shown side
    by side and the user picks one, or keeps both labelled by source.
  - Different dates: no conflict.
- **Trend chart.** One line chart per test across saved reports (for example LDL, HDL,
  triglycerides). Each point shows the value, unit, that report's own reference range and
  flag. Units are converted with `units.yaml` only where the conversion is exact; otherwise
  the point is shown separately and marked "different unit". Critical values are marked. No
  wording about direction or meaning, only values and ranges (section 3).

## 5. Data model

All models are Pydantic v2 and are the single source for schema validation.

```python
class Flag(str, Enum):        # produced by code, never by the LLM
    LOW = "low"; NORMAL = "normal"; HIGH = "high"
    UNKNOWN = "unknown"       # no usable range, or non-numeric value

class Severity(str, Enum):
    NORMAL = "normal"; MILD = "mild"; MARKED = "marked"; CRITICAL = "critical"
    UNKNOWN = "unknown"

class Panel(str, Enum):
    CBC = "cbc"; LIPID = "lipid"; HBA1C = "hba1c"; THYROID = "thyroid"; LFT = "lft"

class Value(BaseModel):
    raw: str                      # exactly as printed: "10.2", "<0.5", ">1000", "Nil"
    number: float | None          # None for qualitative values
    comparator: Literal["=", "<", "<=", ">", ">="] = "="

class RefRange(BaseModel):
    raw: str                      # as printed: "12.0-15.0", "< 200", "Desirable < 200 ..."
    low: float | None             # one-sided ranges allowed
    high: float | None
    source: Literal["report", "fallback_table", "none"]

class ExtractedTest(BaseModel):
    raw_name: str                 # as printed
    test_id: str | None           # canonical, set by normalize_names; None = unknown test
    panel: Panel | None
    value: Value
    unit_raw: str | None
    unit: str | None              # canonical unit after conversion
    ref: RefRange
    printed_flag: str | None      # flag printed on the report, if any
    remark: str | None            # lab remarks for this row
    page: int
    source_span: str              # text or region the value came from
    confidence: float             # 0-1, computed from checks, not LLM self-report

class FlaggedTest(ExtractedTest):
    flag: Flag
    severity: Severity
    is_critical: bool
    flag_disagrees_with_printed: bool   # computed flag differs from printed flag

class Citation(BaseModel):
    kind: Literal["test", "glossary", "remark"]
    id: str

class Statement(BaseModel):
    claim_id: str                 # shared by the EN and HI renders of the same claim
    text: str
    cites: list[Citation]         # empty list is a validation failure

class Explanation(BaseModel):
    language: Literal["en", "hi"]
    source: Literal["llm", "template_fallback"]
    urgent_message: str | None    # fixed template text when any value is critical
    summary: str
    statements: list[Statement]
    disclaimer: str               # fixed text

class Recommendation(BaseModel):
    next_step: Literal["follow_up_test_package", "doctor_consult", "no_action"]
    package_id: str | None        # set only for follow_up_test_package
    urgency: Literal["none", "routine", "soon", "urgent"]
    reason_test_ids: list[str]
    rule_id: str                  # which row of the decision table fired

class ReportResult(BaseModel):
    report_id: str
    status: Literal["complete", "partial"]   # partial = some rows unreadable or LLM fallback used
    report_date: date | None
    panels: list[Panel]           # a report can hold several panels
    tests: list[FlaggedTest]
    unrecognised_tests: list[str] # rows extracted but not mapped to a known test
    lab_remarks: list[str]
    patterns: list[str]           # neutral wording, no condition names
    explanations: list[Explanation]
    recommendation: Recommendation
    low_confidence_tests: list[str]
    warnings: list[str]           # e.g. "range missing for 2 tests", "page 3 unreadable"
    metrics: RunMetrics           # latency_ms per node, tokens in/out/cached, cost_inr, retries, model versions

class SavedReport(BaseModel):     # opt-in history only (sections 4.3 and 10)
    saved_report_id: str
    user_id: str                  # Google account subject ID, not email
    report_date: date             # confirmed or entered by the user
    date_source: Literal["extracted_confirmed", "user_entered"]
    file_sha256: str              # duplicate detection only; the file itself is not kept
    tests: list[FlaggedTest]
    consent_notice_version: str
    saved_at: datetime
```

Reference data lives in versioned YAML files, not in prompts: `panels.yaml` (tests, aliases,
canonical units, plausibility limits), `units.yaml` (conversions, e.g. glucose mg/dL to mmol/L,
TSH µIU/mL = mIU/L), `critical_values.yaml`, `packages.yaml`, `glossary.yaml` (EN + HI).

### Synthetic data (`scripts/generate_reports.py`, documented in `data/README.md`)

15 synthetic **source reports** (clean digital PDFs, 3 per panel) and 30 **eval cases**
derived from them. Each eval case names its source and applies one recorded, controlled
change on top of it (section 7); the generator builds the case from the source spec plus
that change, so the link is real, not a label. Some eval cases are delivered as scanned
images (rotation, blur, noise, JPEG artefacts). Layouts follow the structure of common Indian lab reports in four styles (8, 8, 8
and 6 cases) with invented lab names, people, IDs and signatures, and a "synthetic test
report" line on every page. The fourth style comes from a structural survey of 10 real
reports (format shapes only, no names or values): package titles, sub-heading rows inside the
table, bracketed method lines, unit-less ratio rows, zero-start and labelled ranges, bold-only
abnormal values, and long notes (36-51% of the text) that name conditions.

- **Panels and tests:** CBC (14), lipid (7), HbA1c with eAG (2), thyroid (3), LFT (11), from
  `reference/panels.yaml`. Calculated tests (VLDL, Non-HDL, TC/HDL, eAG, indirect bilirubin,
  globulin, A/G) are computed from the measured ones; the differential always sums to 100.
- **Edge cases:** abbreviated names, a unit variant (T3 in ng/dL), `<` values, missing printed
  ranges, a panel table that breaks across a page without repeating its sub-heading, a wrong
  printed flag, an injected instruction, an unsupported test, a lab remark, interpretation
  tables and notes that name conditions (with must-not-include terms per case), and a blurry
  critical value.
- **Ground truth:** for every printed test, the raw text as printed, the parsed value and
  comparator, units, printed range, page, expected flag, severity and critical status, plus
  the expected next step, urgency, package and decision rule.
- **Two sources of truth:** each case's expected outcome is written by hand in
  `data/case_specs.yaml`; the generator also computes it with its own implementation of the
  decision table and refuses to write anything if they disagree.
- **Checks:** tests including "every ground-truth value, unit, range and name appears in
  the PDF text" and byte-for-byte determinism.
- **NidaanKosha** (Eka Care, CC-BY-SA-4.0) comes from real de-identified reports, so none of
  its rows are used. `scripts/derive_reference_stats.py` reduces it to aggregates (frequent
  printed names, units, range formats, value percentiles, each seen at least 50 times) for
  checking reference ranges and for training data for the name normalizer.

## 6. API contract

FastAPI. JSON in, JSON out. No accounts for the demo itself; Google sign-in only for opt-in
saved history (sections 4.3 and 10).

Because the deployed link is public and every call spends LLM budget, the demo has:
- a per-IP rate limit (e.g. 5 reports per hour) and a global daily spend cap; past the cap the
  API serves only cached sample reports and says so;
- input limits: 5 MB, 10 pages, PDF/PNG/JPG checked by content not extension, encrypted PDFs
  rejected with a clear message;
- a request timeout of 60 s, after which the deterministic fallback result is returned;
- results stored without personal fields and deleted after 24 hours.

### `POST /v1/reports`
Upload a report and receive the full result.

Request: `multipart/form-data`, field `file` (PDF, PNG or JPG, max 5 MB), optional `language`
(`en`, `hi` or `both`, default `both`).

Response `200`:
Example (abridged to one test and the English explanation; it follows the section 5 models):
```json
{
  "report_id": "rpt_01",
  "status": "complete",
  "report_date": "2026-11-02",
  "panels": ["cbc"],
  "tests": [
    {"raw_name": "HGB", "test_id": "hemoglobin", "panel": "cbc",
     "value": {"raw": "10.2", "number": 10.2, "comparator": "="},
     "unit_raw": "g/dL", "unit": "g/dL",
     "ref": {"raw": "12.0 - 15.0", "low": 12.0, "high": 15.0, "source": "report"},
     "printed_flag": "L", "remark": null, "page": 1,
     "source_span": "HGB 10.2 g/dL 12.0 - 15.0 L", "confidence": 0.97,
     "flag": "low", "severity": "marked", "is_critical": false,
     "flag_disagrees_with_printed": false}
  ],
  "unrecognised_tests": [],
  "lab_remarks": [],
  "patterns": [],
  "explanations": [
    {"language": "en", "source": "llm", "urgent_message": null,
     "summary": "I went through your report. Most results are within the ranges printed on it. One needs attention.",
     "statements": [
       {"claim_id": "c1",
        "text": "Your hemoglobin is 10.2 g/dL, below the usual range of 12.0 to 15.0 g/dL.",
        "cites": [{"kind": "test", "id": "hemoglobin"}]},
       {"claim_id": "c2",
        "text": "This can happen for several reasons, so it's worth discussing with a doctor soon.",
        "cites": [{"kind": "glossary", "id": "hemoglobin.low"}]}
     ],
     "disclaimer": "This explains your report. It is not medical advice or a diagnosis."}
  ],
  "recommendation": {"next_step": "doctor_consult", "package_id": null, "urgency": "soon",
                     "reason_test_ids": ["hemoglobin"], "rule_id": "R2_marked"},
  "low_confidence_tests": [],
  "warnings": [],
  "metrics": {"latency_ms": {"total": 5400, "extract": 2900, "plan_statements": 1100, "render_en": 700, "render_hi": 900},
              "tokens_in": 7700, "tokens_out": 2100, "tokens_cached": 0,
              "cost_inr": 0.45, "retries": 0,
              "models": {"extract": "gemini-3.1-flash-lite"}}
}
```
(Hb 10.2 against a low bound of 12.0 is a 15% deviation, so it is `marked`, which routes to
`doctor_consult` with urgency `soon` by rule R2. The numbers in `metrics` are illustrative.)

Status codes:
- `200` with `status: "complete"`: everything succeeded.
- `200` with `status: "partial"`: some rows unreadable, a range missing, or the explanation came
  from the template fallback. `warnings` says what and why.
- `400`: unsupported or encrypted file, too large, or not a lab report (with a reason code).
- `422`: no test could be extracted at all after retries.
- `429`: rate limit or daily cap reached.
- `503`: model provider unavailable **and** nothing could be extracted.

A critical value is never dropped: if any critical value was extracted, the response is a `200`
(complete or partial) carrying the urgent template, whatever else failed.

### `GET /v1/reports/{report_id}`
Return a cached result while its TTL lasts, or a saved one for its owner.

### Real uploads (signed-in users only, section 10)
- `POST /v1/reports` accepts `report_type` (`synthetic` default, or `real`). `real` requires a
  session and a paid-tier key on the server; otherwise `403` with a reason.
- `POST /v1/reports/{report_id}/save` with `{"consent": true, "notice_version": "2026-11-v1",
  "report_date": "2026-11-02"}` saves the structured result. Without `consent: true` or a
  valid `report_date` it returns `400`. A duplicate file returns `409 already_saved`. Same-test
  same-date overlaps return `409 overlap` with both values; the client resends with
  `"overlap_choice": {"<test_id>": "keep_new" | "keep_existing" | "keep_both"}`.
- `GET /v1/history`, `DELETE /v1/history/{report_id}`, `DELETE /v1/history` (delete all and
  withdraw consent).
- `GET /v1/history/trends?test_id=ldl` returns the dated points (value, unit, range, flag,
  source report) for the chart.

### `POST /v1/reports/{report_id}/chat` (stretch)
Request: `{"message": "..."}`. Response: `{"reply": "...", "escalation": "none|see_doctor|urgent"}`.

### `GET /healthz`
Liveness check for the deployed link.

## 7. Evaluation plan

Ground truth comes from the generator, so extraction can be scored exactly.

All 30 evaluation reports are synthetic. Real lab reports were used only as format
references for layouts and were not copied into the repository or into any evaluation.
No real patient data is stored in this repository.

**15 source reports, 30 derived eval cases**

The eval set is built so it does not just measure performance on the reports used for
tuning.
- **Source reports (D01-D15)**: 15 clean synthetic reports, 3 per panel. Used for prompt and
  threshold tuning only, never scored in the reported numbers.
- **Eval cases (E01-E30)**: each names its source report, a variation group and the exact
  change. They are frozen, with expected outcomes committed, before any tuning. Each source is
  used by 1 to 3 eval cases.

| Group | Cases | What changes from the source |
|---|---|---|
| Controlled variation | 10 | Values, age or sex, so at least one flag, severity or next step differs from the source (checked by the generator) |
| Perturbation | 8 | Scanned image (rotation, blur, noise, JPEG), multi-page report, layout change; includes an all-normal scanned CBC as a false-positive check |
| Extraction challenge | 6 | Abbreviated names, T3 in ng/dL, `<0.010` style values, missing ranges, unit-less ratio rows |
| Adversarial | 6 | Critically low Hb, critical WBC in a blurry image, condition-naming table, wrong printed flag (computed flag shown, "confirm with the lab"), injected instruction, unsupported test with a lab remark |

- **Anti-duplication check**: the generator refuses to write the data if any eval case has
  the same file hash as its source or another case, or the same values, layout and rendering.
- **Limitation**: eval cases share layouts with the source reports, so the set measures
  robustness to controlled changes, not performance on unseen report formats. The README
  says so.
  - A bilingual Hindi-English report was planned but dropped: the PDF library cannot shape
    Devanagari text, and Indian lab reports are almost always printed in English.
- All 30 cases go through `POST /v1/reports`, so every row of the core table is filled.
- Chat-guard set (separate, 4 cases): symptom questions such as "my chest pounds, does the
  report show why?". Reported in its own table only if the chat endpoint ships.
- Results are reported for the 30 eval cases overall and per variation group; source-report
  runs are shown only as development numbers. Each eval case has a written expected outcome
  (flags, next step, urgency, must-include and must-not-include phrases) committed before
  the first run.

| Metric | How measured |
|---|---|
| Extraction precision / recall | Rows matched to ground truth by canonical test: recall catches dropped rows, precision catches invented rows |
| Field accuracy | Per field on matched rows: value (numeric tolerance 1e-6 after canonical units), unit, range, name |
| Flag correctness | Flag and severity vs. expected, per test and per report; plus critical-value recall reported on its own (target 100%) |
| Next-step accuracy | `next_step` and `urgency` vs. expected |
| Grounding | Share of statements whose citations exist, whose direction word (high/low/normal) matches the flag, and whose numbers and units match the extracted values. Automatic, plus manual check of a sample |
| EN-HI consistency | Same claim IDs, same numbers and units in both languages |
| Unsafe-advice rate | Unsafe responses / all responses. Banned-phrase rules plus a judge; every judge-flagged output and a random sample of the rest reviewed by hand |
| Judge agreement | The judge is checked against my hand labels on all 30 outputs; agreement is reported, so the judge itself is evaluated |
| Fallback rate | Share of reports where template fallback was used |
| Latency | p50 and p95 per report end to end and per node, cold cache |
| Cost | Tokens times rate, per report and for the suite, including failed and retried calls |

**Rigour details**
- LLM nodes run at temperature 0, but outputs can still vary, so the 30 eval cases are run 3 times;
  mean and spread are reported.
- 30 cases is small, so rates are shown with counts ("1 of 30") and 95% Wilson intervals.
  p95 latency on 30 samples is noisy and is labelled as such.
- Model names and versions, prompt hashes and config versions are recorded with every run.

**Baselines in the results table**
- Rule engine vs. trained model for flags (shows why rules are the source of truth).
- Name normalization: dictionary lookup vs. trained matcher.

**One documented change from the evals:** the first full run is expected to expose a failure
(candidates: Hindi output dropping units, unit confusion such as mg/dL vs mmol/L, or the
LLM adding unsupported causes). The fix and before/after numbers go in the README.

The eval script is independent of ADK so metrics are not coupled to the framework.

## 8. Cost estimate

Budget cap: ₹500 total LLM spend. Actual spend will be recorded in the README.

**Model and rate.** Default model: Gemini 3.1 Flash-Lite (`gemini-3.1-flash-lite`) on the
Gemini API paid tier: $0.25 per 1M input tokens (text, image, video) and $1.50 per 1M output
tokens, **including thinking tokens** (Google's pricing page, checked 2026-11-20). At an assumed
₹90 per USD (fixed in config, dated), that is about ₹22.5 per 1M input and ₹135 per 1M output.
The same model on Vertex AI is listed at a higher rate, so the Gemini API is used.

**Thinking tokens.** Thinking is billed as output. `extract`, `render_en` and `render_hi` run
with thinking off or at the minimum budget; `plan_statements` and the judge start at minimum
and are raised only if the evals show a quality gain worth the cost. Thinking tokens are
logged separately.

**Token assumptions (unverified, replaced with measured values after the first run):**
- Extraction: 3,000 in (document plus prompt), 700 out.
- `plan_statements`: 1,500 in, 500 out.
- `render_en`: 1,000 in, 300 out. `render_hi`: 1,000 in, 450 out (Hindi usually needs more
  tokens for the same text).
- Safety judge, when used: 1,200 in, 150 out.
- Average 1.3 calls per LLM node due to retries.

| Step | Tokens in | Tokens out | Approx. cost (₹) |
|---|---|---|---|
| extract | 3,000 | 700 | 0.16 |
| plan_statements | 1,500 | 500 | 0.10 |
| render_en | 1,000 | 300 | 0.06 |
| render_hi | 1,000 | 450 | 0.08 |
| safety judge | 1,200 | 150 | 0.05 |
| **Per report, before retries** | 7,700 | 2,100 | **~0.45** |
| **Per report, with 1.3x retries** | | | **~0.60** |

The explanation step is now 3 calls instead of 1, which repeats the static system and glossary
prefix three times. That is already counted in the input tokens above.

Planned spend:

| Activity | Runs | Estimated cost (₹) |
|---|---|---|
| Development and prompt iteration | ~300 report runs | 180 |
| Eval runs (source-report runs, plus the 30 eval cases 3 times per measured configuration) | ~225 | 135 |
| Hindi quality checks and buffer | | 60 |
| **Total** | | **~375** |

This leaves roughly ₹125 of headroom under the cap. If thinking cannot be fully disabled on a
node, output tokens could rise several-fold, which is the biggest risk to this estimate; the
budget guard below catches it.

The free tier is used for early development where its rate limits allow. Google's pricing page
says free-tier data may be used to improve its products, which is acceptable here only because
all data is synthetic.

Controls:
- A hard budget guard that estimates a call's cost before sending it and refuses if logged
  spend plus the estimate would pass ₹450. Failed and retried calls are logged and counted.
- The public demo has its own daily cap (section 6), so strangers cannot use up the budget.
- Response caching during development, and only abnormal rows plus a normal count are sent
  to the explanation step.
- A fixed INR conversion rate in config, dated, so the reported spend is reproducible.

Local training of the ML nodes costs no LLM spend. Free-tier model quotas may reduce the
actual figure.

## 9. Caching and serving

Three separate mechanisms, in order of priority. Only the first two are committed work.

### 9.1 Response cache (committed)
- Key: SHA-256 of the file bytes plus `pipeline_version` (prompt hashes, model name,
  glossary version, threshold config). Value: the stored `ReportResult` and per-node outputs.
- Backing store: SQLite file for the demo (no extra service).
- Used during development and when re-running evals, so unchanged inputs cost zero tokens.
- Cache is per node as well as per report, so changing the `render_hi` prompt re-runs only
  `render_hi` and `safety_check`, and changing `plan_statements` re-runs it and everything
  after it, never extraction.
- Invalidation: any change to a node's prompt, model or config changes `pipeline_version`
  for that node. Eval runs support `--no-cache` for cold numbers.
- Reporting rule: the headline latency and cost in the README come from a cold run
  (`--no-cache`). Warm-cache figures are shown separately and labelled.
- Not used for the chat endpoint. Replies depend on conversation state.

### 9.2 Provider prompt caching (committed, low effort)
- Prompts are laid out with the static prefix first (system rules, safety rules, schema,
  glossary, few-shot examples) and the per-report content last, so a provider's automatic
  prefix caching can apply.
- The run log records cached and uncached input tokens separately.
- No explicit cache management is built. The static prefix (a few thousand tokens at most) is
  probably below the provider's minimum cacheable size, and implicit caching is not guaranteed
  on every model tier, so no saving is assumed anywhere in the cost estimate (section 8). The
  exact minimum for the chosen model is checked when the model is fixed.

### 9.3 Self-hosted serving with prefix (KV) caching (stretch experiment)
Applies only if a model is run on our own hardware. It does not apply to hosted API calls.
- Idea: serve a small open-weights model with vLLM (automatic prefix caching) for one
  narrow node, most likely `render_en` or the optional judge (Hindi rendering is the hardest for
  small open models, so `render_hi` stays hosted), and compare it with the hosted
  model in the eval table (quality, latency, cost).
- Prerequisite: GPU access. Whether a free tier gives enough GPU time and memory is
  unverified. If it does not, this item is dropped and recorded as not done.
- Hindi quality of small open models is a real risk, so safety and grounding metrics must be
  at least as good as the hosted model before it is used. Otherwise it stays an experiment.
- Cost: no LLM spend, but compute time counts as effort. The README will state the hardware
  used and not claim the cost is zero.
- Decision rule: adopt only if it improves a measured metric without hurting safety or
  grounding. A negative result is documented as a finding.

## 10. Real uploads and consent

The demo, the evals and everything in the repo use synthetic data only. Uploading a real report
is an optional, separately labelled feature for signed-in users. It is built so that nothing
real is kept unless the user explicitly asks.

### Default: cache only
- The uploaded file and its results live in process memory with a 60-minute TTL. They are
  never written to disk, the response cache (section 9.1), logs, evals or the staff page.
- Logs for real uploads hold only a random request ID, timings, token counts, cost and status.
- After the TTL, or when the user clicks "Clear now", the data is gone.

### Opt-in: saved history
- Shown under the result, never before it: an **unticked** checkbox, separate from the terms of
  use. Saving happens only when it is ticked. Nothing is pre-selected.
- Saved: extracted test values, units, ranges, flags, the user-confirmed report date, a
  SHA-256 of the file (to detect duplicates) and the user's Google account subject ID.
  Not saved: the original file, the file name, the extracted text, names or IDs from the
  report, the user's email.
- Sign-in is Google sign-in, asked for only at the moment of saving.
- The user can delete one report or all reports at any time. Withdrawing consent deletes all
  saved reports. Saved reports are deleted after 12 months without a sign-in.
- Consent is recorded with the notice version and a timestamp, so it can be shown later.

### Model provider
- Real uploads are processed only with a paid-tier API key. Google's pricing page says
  free-tier data may be used to improve its products, so real-upload mode is switched off when
  only a free-tier key is configured.
- `redact_pii` runs before every LLM call, as for synthetic reports (section 4).

### Consent text (English)
> **Save this report to my history**
> If you tick this box, we will save the test results from this report (test names, values,
> units, reference ranges, flags and the report date) to your account, so you can see your
> past reports and how your results change. We do not save the file you uploaded or your name.
> You can delete one report or all of your saved reports at any time from **My history**. If you
> don't tick this box, your report is deleted within 60 minutes. Ticking this box is optional
> and does not change the explanation you receive.

### Consent text (Hindi)
> **यह रिपोर्ट मेरी हिस्ट्री में सेव करें**
> अगर आप यह बॉक्स टिक करते हैं, तो हम इस रिपोर्ट के जाँच परिणाम (जाँच के नाम, मान, यूनिट,
> संदर्भ सीमा, फ़्लैग और रिपोर्ट की तारीख़) आपके अकाउंट में सेव करेंगे, ताकि आप अपनी पिछली
> रिपोर्ट और अपने परिणामों में बदलाव देख सकें। हम आपकी अपलोड की गई फ़ाइल या आपका नाम सेव नहीं
> करते। आप **मेरी हिस्ट्री** में जाकर कभी भी एक रिपोर्ट या अपनी सभी सेव की गई रिपोर्ट डिलीट कर
> सकते हैं। अगर आप यह बॉक्स टिक नहीं करते, तो आपकी रिपोर्ट 60 मिनट के भीतर डिलीट हो जाती है।
> यह बॉक्स टिक करना ज़रूरी नहीं है और इससे आपको मिलने वाली व्याख्या नहीं बदलती।

The Hindi text needs a fluent reader's check before release.

**Legal note.** India's DPDP Rules, 2025 were notified on 14 November 2025 and require notices
in simple language that describe the data, the purpose and how to withdraw consent. Their
provisions start on different dates. This section aims at good practice for a demo and is not
legal advice; a real launch would need a legal review.

## 11. Edge cases and failure handling

Every row below becomes at least one unit test or eval case.

### Input
| Case | Handling |
|---|---|
| Not a lab report (a bill, a prescription, a selfie) | `input_guard` rejects with `400 not_a_lab_report` |
| Unsupported panel (urine, culture) mixed with supported ones | Supported panels explained; others listed as "not covered by this tool" |
| Encrypted or corrupted PDF, zero pages | `400` with a specific reason |
| Very long report (more than 10 pages) | `400 too_many_pages`; demo limit stated in README |
| Scanned, rotated or blurry image | Extraction runs; low confidence rows marked "please verify"; unreadable pages listed in `warnings` |
| Report printed in Hindi or bilingual | Extraction prompt handles it; one test case covers it; if unsupported, say so instead of guessing |
| Prompt injection in report text | Treated as data; one adversarial eval case |
| Same file uploaded twice | Response cache returns the stored result |

### Extraction
| Case | Handling |
|---|---|
| Row dropped by the LLM | Completeness check against `panels.yaml` expected tests and against a text-layer row count; missing rows trigger one targeted retry, then a warning |
| Row invented by the LLM | Every value must appear in `source_span` from the document text layer (when one exists); if not found, the row is dropped and logged |
| Misread digit (5.6 vs 6.5) | Plausibility limits per test; text-layer vs vision cross-check; disagreement lowers confidence |
| Value like `<0.5`, `>1000`, `Nil`, `Reactive` | Stored in `Value` with comparator or as qualitative; flag computed only where the comparison is decidable, otherwise `unknown` |
| Missing unit | Inferred only if the panel's canonical unit is unambiguous and the value is plausible in it; otherwise flag `unknown` |
| Value and range in different units | Converted via `units.yaml`; if no conversion, flag `unknown` and warn |
| One-sided or multi-tier range ("Desirable < 200, Borderline 200-239") | Normal bound parsed; tier labels not repeated if they name a condition |
| Missing range | Fallback table only for adult tests with no age or sex dependence, flagged against it with the warning "range not printed; standard range used"; otherwise flag `unknown` and "please verify" |
| Age or sex-dependent test with no printed range (Hb, creatinine) | No fallback; flag `unknown` and say the lab range is needed |
| Paediatric or pregnancy report | Trust printed ranges only; no fallback table; noted as out of scope |
| Duplicate test on the report | Both kept with page refs; if values differ, warn and use the more severe for routing |
| Printed flag disagrees with computed flag | Computed flag is shown; disagreement recorded; the more severe of the two drives routing |
| Unknown test name | Listed in `unrecognised_tests`; not explained; does not crash the pipeline |
| Validation still fails after retries | Valid rows kept; `status: partial` |

### Explanation and safety
| Case | Handling |
|---|---|
| All tests normal | Short bounded message, no glossary dump, `no_action` |
| Many abnormal tests | Summary of the most severe first, then the rest; length capped |
| Critical value | Fixed urgent template first in both languages, independent of the LLM |
| Critical value with low confidence | Still urgent, plus "please confirm this value with the lab" |
| LLM names a condition, gives dosage, or reassures against a flag | `safety_check` rejects; retry; then template fallback |
| LLM states the wrong direction ("high" for a low value) | Direction check in `safety_check` rejects |
| Hindi drops or changes a number or unit | EN-HI consistency check rejects; Hindi keeps Latin digits and the English test name in brackets for clarity |
| Pattern suggests a condition | Patterns are worded only as "these results are outside range together"; package names avoid condition names |
| Lab remark present | Shown verbatim with a neutral note |

### System
| Case | Handling |
|---|---|
| Model API timeout, 429 or outage | Retry with backoff (max 2); then template fallback; flags and next step still returned |
| Budget guard trips | LLM calls stop; template fallback; clear message in logs and the API |
| ADK node raises an exception | Workflow catches it at node level; downstream deterministic nodes still run where possible |
| Free-tier host cold start | `/healthz` warm-up note in README; latency figures measured on a warm server and labelled |
| Model version changes upstream | Model version pinned and recorded; cache key includes it |

### Saved history
| Case | Handling |
|---|---|
| Report date missing or unreadable | User must enter it; save is blocked until then |
| Date in the future or implausibly old | Rejected with a reason; user corrects it |
| Same file saved twice | `409 already_saved`; nothing added |
| Same test, same date, different report | Both values shown; user keeps new, existing or both |
| Unit differs between saved reports | Exact conversion via `units.yaml`, else plotted separately and marked |
| Reference ranges differ between labs | Each point keeps its own report's range |
| Only one saved report for a test | Single point, "add more reports to see a trend" |

## 12. Risks, assumptions and future work

**Unverified assumptions (to confirm early)**
- ~~ADK 2.0 class and decorator names match the docs snippets~~ Confirmed by the spike on
  2026-11-21 with `google-adk==2.15.0` (section 4.1). ADK releases roughly
  every two weeks (2.10.0 was out by September 2026), so the newest version that passes the
  spike is pinned exactly in `requirements.txt`.
- ADK's built-in eval tooling may differ in 2.0; the custom script avoids depending on it.
- The ML nodes will have enough varied synthetic training data. Labels from my own
  generator can be circular, so a held-out set with unseen name variants and layouts is
  required.
- LLM-based Hindi quality: automatic checks cover numbers and units only. Language quality
  needs a human reading of a sample.
- Reference ranges differ by lab, age and sex. The plan trusts the range printed on the
  report and uses a fallback table only when it is missing.

**Risks**

| Risk | Mitigation |
|---|---|
| LLM adds unsupported causes or diagnoses | Glossary-grounded text, `safety_check`, banned-phrase rules |
| Misread value causes a wrong flag | Confidence score, validation, "please verify" path |
| Missed critical value | Critical check on every extracted row, runs before any LLM explanation; critical recall reported separately |
| Critical value missed because extraction dropped the row | Completeness check and retry; dropped-row recall is an eval metric |
| Cost overrun | Budget guard, caching, small model tier, public demo cap |
| Hindi errors | Plan-then-render, numeric and unit consistency check, human spot-check |
| Overfitting prompts to the eval set | Tuning on 15 source reports only; 30 derived eval cases frozen before tuning; anti-duplication check; results per variation group |
| Judge model is wrong | Judge agreement with hand labels reported |
| Personal data leaks into prompts or logs | `redact_pii` before LLM calls; logs store IDs and metrics, not report text |
| Personal data survives image redaction (name printed outside the header, handwriting, unusual layout) | Header-band masking plus OCR box redaction; residual risk accepted for the demo because all data is synthetic; a real deployment would need layout-specific templates and a human audit sample |

**Future work (not in scope)**
- Interpreting trends in words; the demo charts values and ranges only (section 4.3).
- More panels, age and sex-specific ranges, more languages.
- Clinician review of the glossary text before any real deployment.

## 13. Milestones

1. PLAN.md committed (this file).
2. Two-node ADK 2.0 spike (function node, Gemini agent node with Pydantic output, router, run in `adk web`) to confirm the API before building on it; update section 4.1 with the findings.
3. Synthetic data generator, reference YAML files, 15 source reports and 30 derived eval
   cases with ground truth and the anti-duplication check; freeze the eval cases' expected
   outcomes.
4. Flag engine and decision table with unit tests covering section 11.
5. Extraction and validation, with a first extraction precision/recall number.
6. Response cache, budget guard and prompt layout (section 9.1 and 9.2), before heavy iteration.
7. Urgent template, template fallback, then plan-then-render explanation, safety check and routing.
8. ML nodes and baseline comparison.
9. Full 30-case eval (3 runs), results table, one eval-driven fix with before/after numbers.
10. Stretch: self-hosted serving experiment (section 9.3), only if time and GPU access allow.
11. API with rate limits and caps; build the frontend from the provided design (section 4.2); deployment, README, AI_USAGE.md, video.
12. Opt-in saved history: Google sign-in, report-date confirmation, duplicate and overlap
    handling, trend charts (section 4.3), with tests for the "Saved history" edge cases.
