"""ML function nodes (PLAN.md section 4): saved scikit-learn models, loaded lazily and cached."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import joblib

MODELS_DIR = Path(__file__).resolve().parents[3] / "models"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=None)
def load_model(name: str, directory: str | None = None):
    """Load models/<name>.joblib only if its sha256 matches <name>.card.json (joblib is pickle)."""
    base = Path(directory or MODELS_DIR)
    path, card = base / f"{name}.joblib", base / f"{name}.card.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run scripts/train_ml.py")
    try:
        expected = json.loads(card.read_text(encoding="utf-8"))["sha256"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError(f"{card} missing or has no sha256; refusing to load {path.name}") from e
    if file_sha256(path) != expected:
        raise ValueError(f"{path.name} sha256 does not match its model card; refusing to load")
    return joblib.load(path)
