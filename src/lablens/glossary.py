"""glossary_lookup node (PLAN.md section 4): curated per-test text, no LLM."""
from __future__ import annotations

from lablens import reference


def load_glossary() -> dict[str, dict]:
    return reference.load_yaml("glossary.yaml")["tests"]


def glossary_lookup(test_ids: list[str | None]) -> dict[str, dict]:
    """Entries for known test ids, in input order; unknown or None ids are skipped."""
    gl = load_glossary()
    return {tid: gl[tid] for tid in test_ids if tid and tid in gl}


def glossary_ids(entries: dict[str, dict] | None = None) -> set[str]:
    """Citable glossary ids, e.g. "HB.measures", "HB.low"."""
    entries = load_glossary() if entries is None else entries
    return {f"{tid}.{k}" for tid, e in entries.items() for k in ("measures", "low", "high")
            if k in e}
