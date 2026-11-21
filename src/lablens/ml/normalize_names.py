"""normalize_names (ML) node: printed test name -> canonical test_id, or None (abstain).

Model: char n-gram TF-IDF + 1-nearest-neighbour (cosine) with an abstain threshold tuned for
zero wrong mappings on the dev set. Baseline: normalised dictionary lookup of panels.yaml names.
"""
from __future__ import annotations

from lablens import reference
from lablens.ml import load_model
from lablens.ml.data import _aliases, norm
from lablens.schemas import ExtractedTest


def dictionary_lookup(raw: str, names: dict[str, str] | None = None) -> str | None:
    if names is None:
        names = {norm(a): tid for tid, t in reference.load_tests().items() for a in _aliases(t)}
    return names.get(norm(raw or ""))


def scores(raw: str, m: dict) -> tuple[str | None, float, float]:
    """(best test_id, its cosine similarity, margin over the best different test_id)."""
    k = min(50, len(m["labels"]))
    dist, idx = m["nn"].kneighbors(m["vec"].transform([raw.strip().lower()]), n_neighbors=k)
    best: dict[str, float] = {}
    for d, i in zip(dist[0], idx[0]):
        best.setdefault(m["labels"][i], 1.0 - float(d))
    ranked = sorted(best.values(), reverse=True) + [0.0]
    return max(best, key=best.get), ranked[0], ranked[0] - ranked[1]


def predict(raw: str, model: dict | None = None) -> tuple[str | None, float]:
    """(test_id or None, similarity). Abstains below the similarity threshold or when the
    runner-up test is within `margin` (e.g. HDL vs LDL), so near-misses become None."""
    m = model or load_model("normalize_names")
    if not raw or not raw.strip():
        return None, 0.0
    tid, sim, margin = scores(raw, m)
    return (tid if sim >= m["threshold"] and margin >= m["margin"] else None), sim


def normalize_name_with_source(raw: str) -> tuple[str | None, str | None]:
    """Dictionary hit first ("dictionary"); model only as a fallback ("model", must be verified)."""
    if tid := dictionary_lookup(raw):
        return tid, "dictionary"
    tid = predict(raw)[0]
    return tid, ("model" if tid else None)


def normalize_name(raw: str) -> str | None:
    return normalize_name_with_source(raw)[0]


def normalize_names(tests: list[ExtractedTest]) -> tuple[list[ExtractedTest], list[str]]:
    """Function node: fill test_id where unset; returns the rows plus raw names mapped by the model."""
    out, model_mapped = [], []
    for t in tests:
        if t.test_id:
            out.append(t)
            continue
        tid, source = normalize_name_with_source(t.raw_name)
        if source == "model":
            model_mapped.append(t.raw_name)
        out.append(t.model_copy(update={"test_id": tid}))
    return out, model_mapped
