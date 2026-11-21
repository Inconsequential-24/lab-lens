"""Loaders for versioned reference YAML (PLAN.md section 5)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "reference"


@lru_cache(maxsize=None)
def load_yaml(name: str, directory: str | None = None) -> dict:
    path = Path(directory or REFERENCE_DIR) / name
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a YAML mapping")
    return data


def load_tests() -> dict[str, dict]:
    return load_yaml("panels.yaml")["tests"]


def load_packages() -> dict[str, dict]:
    return load_yaml("packages.yaml")["packages"]


def load_critical_values() -> dict[str, dict]:
    # Critical thresholds currently live in panels.yaml under each test's `critical` key.
    return {tid: t["critical"] for tid, t in load_tests().items() if t.get("critical")}


def fallback_range(test_id: str | None) -> tuple[float | None, float | None] | None:
    """Adult range independent of age/sex, or None when no safe fallback exists."""
    ref = (load_tests().get(test_id or "") or {}).get("ref") or {}
    bounds = ref.get("all")
    if not bounds or (bounds[0] is None and bounds[1] is None):
        return None
    return bounds[0], bounds[1]


def is_informational(test_id: str | None) -> bool:
    """Tests with no reference range at all (eAG) never trigger 'please verify'."""
    ref = (load_tests().get(test_id or "") or {}).get("ref") or {}
    return ref.get("all") == [None, None]


def load_unit_conversions() -> dict[str, dict]:
    """Per-test {equivalent, alt_units}: panels.yaml alt_units merged with the demo table."""
    extra = load_yaml("unit_conversions.yaml")["tests"]
    out: dict[str, dict] = {}
    for tid, t in load_tests().items():
        x = extra.get(tid) or {}
        out[tid] = {"unit": t.get("unit"), "equivalent": list(x.get("equivalent") or []),
                    "alt_units": {**(t.get("alt_units") or {}), **(x.get("alt_units") or {})}}
    return out
