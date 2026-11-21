"""Pydantic v2 models from PLAN.md section 5."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Flag(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    NORMAL = "normal"
    MILD = "mild"
    MARKED = "marked"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class Panel(str, Enum):
    CBC = "cbc"
    LIPID = "lipid"
    HBA1C = "hba1c"
    THYROID = "thyroid"
    LFT = "lft"


class Value(BaseModel):
    raw: str
    number: float | None
    comparator: Literal["=", "<", "<=", ">", ">="] = "="


class RefRange(BaseModel):
    raw: str
    low: float | None
    high: float | None
    source: Literal["report", "fallback_table", "none"]


class ExtractedTest(BaseModel):
    raw_name: str
    test_id: str | None
    panel: Panel | None
    value: Value
    unit_raw: str | None
    unit: str | None
    ref: RefRange
    printed_flag: str | None
    remark: str | None
    page: int
    source_span: str
    confidence: float = Field(ge=0.0, le=1.0)


class FlaggedTest(ExtractedTest):
    flag: Flag
    severity: Severity
    is_critical: bool
    flag_disagrees_with_printed: bool
    warnings: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    kind: Literal["test", "glossary", "remark"]
    id: str


class Statement(BaseModel):
    claim_id: str
    text: str
    cites: list[Citation] = Field(min_length=1)


class Explanation(BaseModel):
    language: Literal["en", "hi"]
    source: Literal["llm", "template_fallback"]
    urgent_message: str | None
    summary: str
    statements: list[Statement]
    disclaimer: str


class Recommendation(BaseModel):
    next_step: Literal["follow_up_test_package", "doctor_consult", "no_action"]
    package_id: str | None
    urgency: Literal["none", "routine", "soon", "urgent"]
    reason_test_ids: list[str]
    rule_id: str
    note: str | None = None  # "please verify" / "please confirm" text; not in PLAN.md section 5


class RunMetrics(BaseModel):
    # PLAN.md names the contents but does not define field types.
    latency_ms: dict[str, float] = Field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    cost_inr: float = 0.0
    retries: int = 0
    model_versions: dict[str, str] = Field(default_factory=dict)


class ReportResult(BaseModel):
    report_id: str
    status: Literal["complete", "partial"]
    report_date: date | None
    panels: list[Panel]
    tests: list[FlaggedTest]
    unrecognised_tests: list[str]
    lab_remarks: list[str]
    patterns: list[str]
    explanations: list[Explanation]
    recommendation: Recommendation
    low_confidence_tests: list[str]
    warnings: list[str]
    metrics: RunMetrics


class SavedReport(BaseModel):
    saved_report_id: str
    user_id: str
    report_date: date
    date_source: Literal["extracted_confirmed", "user_entered"]
    file_sha256: str
    tests: list[FlaggedTest]
    consent_notice_version: str
    saved_at: datetime


class ExtractedRow(BaseModel):
    """One row as read by the `extract` LLM; validate turns it into ExtractedTest."""
    raw_name: str
    test_id_hint: str | None = None  # LLM's guess from the catalog; aliases win in validate
    value_raw: str
    value_number: float | None = None
    comparator: Literal["=", "<", "<=", ">", ">="] = "="
    unit_raw: str | None = None
    ref_raw: str = ""
    ref_low: float | None = None
    ref_high: float | None = None
    printed_flag: str | None = None
    remark: str | None = None
    page: int = 1
    source_span: str = ""


class Extraction(BaseModel):
    """`extract` LLM output_schema."""
    tests: list[ExtractedRow]
    report_date: str | None = None  # ISO yyyy-mm-dd as read; parsed in validate
    lab_remarks: list[str] = Field(default_factory=list)


class ValidatedReport(BaseModel):
    """`validate` output."""
    tests: list[ExtractedTest]
    report_date: date | None
    panels: list[Panel]
    unrecognised_tests: list[str]
    lab_remarks: list[str]
    low_confidence_tests: list[str]
    dropped_rows: list[str]
    warnings: list[str]
