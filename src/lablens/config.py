"""Constants for caching and budget (PLAN.md sections 8 and 9.1). Env vars override defaults."""
import os
from pathlib import Path


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


MODEL_NAME = os.environ.get("LABLENS_MODEL", "gemini-3.1-flash-lite")

# Gemini API paid-tier rates, checked 2026-11-20 (USD per 1M tokens; thinking billed as output).
USD_PER_M_INPUT = _float("LABLENS_USD_PER_M_INPUT", 0.25)
USD_PER_M_OUTPUT = _float("LABLENS_USD_PER_M_OUTPUT", 1.50)
INR_PER_USD = _float("LABLENS_INR_PER_USD", 90.0)
INR_PER_USD_DATE = "2026-11-20"

BUDGET_CAP_INR = _float("LABLENS_BUDGET_CAP_INR", 500.0)
# Guard refuses a call once logged spend plus its estimate would pass this (section 8).
BUDGET_GUARD_INR = _float("LABLENS_BUDGET_GUARD_INR", 450.0)

CACHE_DIR = Path(os.environ.get("LABLENS_CACHE_DIR", "cache"))
RESPONSE_CACHE_PATH = CACHE_DIR / "responses.sqlite"
BUDGET_DB_PATH = CACHE_DIR / "budget.sqlite"

# Static-prefix-first prompt layout (section 9.2), for provider prefix caching.
PROMPT_PREFIX_ORDER = ("system_rules", "safety_rules", "schema", "glossary", "few_shot")

# Public demo API limits (PLAN.md section 6).
DAILY_CAP_INR = _float("LABLENS_DAILY_CAP_INR", 50.0)  # global LLM spend per UTC day
RATE_LIMIT_REPORTS_PER_HOUR = int(_float("LABLENS_RATE_LIMIT_PER_HOUR", 30))  # per IP, POST /v1/reports
RATE_LIMIT_READS_PER_MINUTE = int(_float("LABLENS_RATE_LIMIT_READS_PER_MINUTE", 60))  # per IP, other endpoints
REQUEST_TIMEOUT_S = _float("LABLENS_REQUEST_TIMEOUT_S", 60.0)
SYNTHETIC_RESULT_TTL_S = 24 * 3600  # results deleted after 24 h (section 6)
REAL_RESULT_TTL_S = 60 * 60  # real uploads: process memory only, 60 min (section 10)
# Real uploads need a paid-tier key (section 10); set to 1 only when the configured key is paid tier.
PAID_TIER_KEY = os.environ.get("LABLENS_PAID_TIER_KEY", "") == "1"
GOOGLE_CLIENT_ID = os.environ.get("LABLENS_GOOGLE_CLIENT_ID", "")  # ID-token audience
FRONTEND_DIST = Path(os.environ.get("LABLENS_FRONTEND_DIST", "frontend/dist"))

# Opt-in saved history (PLAN.md sections 4.3 and 10).
HISTORY_DB_PATH = CACHE_DIR / "history.sqlite"
HISTORY_RETENTION_DAYS = 365  # deleted after 12 months without a sign-in
HISTORY_MIN_REPORT_DATE = "1990-01-01"
