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
