"""Train the ML nodes deterministically and save models/*.joblib plus model cards.

Usage: .venv/bin/python scripts/train_ml.py [--out DIR]
Uses only panels.yaml/packages.yaml, the flag engine and D* ground truth. E* cases are never read.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors
from sklearn.pipeline import make_union
from sklearn.tree import DecisionTreeClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lablens import reference  # noqa: E402
from lablens.ml import MODELS_DIR, data, file_sha256  # noqa: E402
from lablens.ml.normalize_names import scores  # noqa: E402


OUT = MODELS_DIR


def _save(name: str, obj, card: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.joblib"
    joblib.dump(obj, path, compress=3)
    card.update(model=name, sklearn_version=sklearn.__version__, seed=data.SEED,
                size_bytes=path.stat().st_size, sha256=file_sha256(path))  # checked by load_model
    (OUT / f"{name}.card.json").write_text(json.dumps(card, indent=2) + "\n")


def fit_names(train):
    vec = make_union(TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True),
                     TfidfVectorizer(analyzer="word", token_pattern=r"[a-z0-9]+", sublinear_tf=True))
    X = vec.fit_transform([n.strip().lower() for n, _ in train])
    return {"vec": vec, "nn": NearestNeighbors(n_neighbors=1, metric="cosine").fit(X),
            "labels": [t for _, t in train], "threshold": 0.0, "margin": 0.0}


def train_names() -> dict:
    sp = data.name_splits()
    m = fit_names(sp["train"])
    # Tune (threshold, margin) on dev only: zero wrong mappings first, then max accuracy.
    sc = [(scores(n, m), t) for n, t in sp["dev"]]
    grid = [(th / 100, mg / 100) for th in range(50, 96, 2) for mg in range(0, 31, 2)]

    def rank(g):
        got = [tid if s >= g[0] and mg >= g[1] else None for (tid, s, mg), _ in sc]
        wrong = sum(p is not None and p != t for p, (_, t) in zip(got, sc))
        return (wrong, -sum(p == t for p, (_, t) in zip(got, sc)), g)
    _, _, (th, mg) = min(rank(g) for g in grid)
    m = fit_names(sp["train"] + sp["dev"][: sum(t is not None for _, t in sp["dev"])]) | {
        "threshold": th, "margin": mg}
    _save("normalize_names", m, {
        "type": "char 2-4gram + word TF-IDF, nearest-neighbour cosine, abstain on low similarity or small margin",
        "threshold": m["threshold"], "margin": m["margin"], "n_train": len(m["labels"]), "n_dev": len(sp["dev"]),
        "n_heldout": len(sp["heldout"]),
        "split": f"train rules {data.TRAIN_RULES}; held-out rules {data.HELDOUT_RULES}; "
                 "~1/3 of aliases per test held out entirely; unknown names split dev/held-out; "
                 "D* printed names in train; E* never used",
    })
    return m


def train_patterns() -> None:
    sets = data.synth_flag_sets(4000, data.SEED) + data.gt_flag_sets("D")
    X = [data.flag_vector(f) for f in sets]
    y = [data.pattern_labels(f) for f in sets]
    clf = DecisionTreeClassifier(random_state=data.SEED, max_depth=8).fit(X, y)
    _save("pattern_model", {"clf": clf, "patterns": list(reference.load_packages())}, {
        "type": "multi-output DecisionTree on per-test low/high indicators",
        "n_train": len(X), "labels": "packages.yaml requires_* patterns (rule-derived, circular)",
        "split": "train seed SEED (4000 synthetic) + D*; held-out seed SEED+1 minus duplicates; E* final",
    })


def train_flags() -> None:
    train_ids, held_ids = data.flag_test_split()
    rows = data.flag_rows(train_ids, 200, data.SEED)
    clf = DecisionTreeClassifier(random_state=data.SEED, max_depth=10).fit(
        [r[0] for r in rows], [r[1] for r in rows])
    _save("flag_model", {"clf": clf}, {
        "type": "DecisionTree on (value, low, high); evidence only, flag_engine stays source of truth",
        "n_train": len(rows), "train_tests": train_ids, "heldout_tests": held_ids,
        "split": "held out by whole test_id (unseen scales); E* rows final",
    })


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Train the ML nodes and write .joblib + model cards.")
    ap.add_argument("--out", type=Path, default=MODELS_DIR, help="output directory (default: models/)")
    OUT = ap.parse_args().out
    train_names()
    train_patterns()
    train_flags()
    print("saved to", OUT)
