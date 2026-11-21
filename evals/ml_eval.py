"""Evaluate ML nodes vs baselines; writes evals/results_ml.json (PLAN.md section 7).

Usage: .venv/bin/python evals/ml_eval.py   (after scripts/train_ml.py)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

from sklearn.metrics import f1_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lablens import reference  # noqa: E402
from lablens.decision import _package_match  # noqa: E402
from lablens.ml import data, load_model  # noqa: E402
from lablens.ml.normalize_names import dictionary_lookup, predict  # noqa: E402
from lablens.schemas import Flag  # noqa: E402


def wilson(k: int, n: int, z: float = 1.96) -> dict:
    if n == 0:
        return {"k": 0, "n": 0, "rate": None, "ci95": None}
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"k": k, "n": n, "rate": round(p, 4), "ci95": [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]}


def name_metrics(pairs, fn) -> dict:
    pred = [fn(n) for n, _ in pairs]
    true = [t for _, t in pairs]
    n = len(pairs)
    unk = [p for p, t in zip(pred, true) if t is None]
    lab = lambda x: x or "__none__"  # noqa: E731
    return {
        "accuracy": wilson(sum(p == t for p, t in zip(pred, true)), n),
        "wrong_mapping": wilson(sum(p is not None and p != t for p, t in zip(pred, true)), n),
        "unknown_wrong_mapping": wilson(sum(p is not None for p in unk), len(unk)),
        "abstain": wilson(sum(p is None for p in pred), n),
        "macro_f1": round(f1_score([lab(t) for t in true], [lab(p) for p in pred],
                                   average="macro", zero_division=0), 4),
    }


def eval_names() -> dict:
    sp = data.name_splits()
    m = load_model("normalize_names")
    train_dict = {data.norm(n): t for n, t in sp["train"] + sp["dev"] if t}
    model = lambda s: predict(s, m)[0]  # noqa: E731
    e_names = data.gt_names("E") + [(u, None) for u in data.UNKNOWN_NAMES if u not in
                                     {x for x, t in sp["dev"] if t is None}]
    return {
        "heldout": {"model": name_metrics(sp["heldout"], model),
                    "hybrid_dict_then_model": name_metrics(sp["heldout"], lambda s: dictionary_lookup(s, train_dict) or model(s)),
                    "baseline_dict_train_names": name_metrics(sp["heldout"], lambda s: dictionary_lookup(s, train_dict)),
                    "baseline_dict_all_panels": name_metrics(sp["heldout"], dictionary_lookup)},
        "e_printed_names_plus_heldout_unknowns": {
            "model": name_metrics(e_names, model),
            "hybrid_dict_then_model": name_metrics(e_names, lambda s: dictionary_lookup(s) or model(s)),
            "baseline_dict_all_panels": name_metrics(e_names, dictionary_lookup)},
    }


def _r3(flags):
    ab = {t: SimpleNamespace(flag=Flag(f)) for t, f in flags.items() if f in ("low", "high")}
    return _package_match(ab, reference.load_packages())


def pattern_metrics(sets, fn) -> dict:
    pats = list(reference.load_packages())
    true = [data.pattern_labels(f) for f in sets]
    pred = [fn(f) for f in sets]
    false_pos = sum(p and not t for tv, pv in zip(true, pred) for t, p in zip(tv, pv))
    return {"exact_match": wilson(sum(t == p for t, p in zip(true, pred)), len(sets)),
            "macro_f1": round(f1_score(true, pred, average="macro", zero_division=0), 4),
            "false_pattern": wilson(false_pos, len(sets) * len(pats))}


def eval_patterns() -> dict:
    clf = load_model("pattern_model")["clf"]
    pats = list(reference.load_packages())
    seen = {tuple(data.flag_vector(f)) for f in data.synth_flag_sets(4000, data.SEED) + data.gt_flag_sets("D")}
    held = [f for f in data.synth_flag_sets(1000, data.SEED + 1) if tuple(data.flag_vector(f)) not in seen]
    model = lambda f: [int(x) for x in clf.predict([data.flag_vector(f)])[0]]  # noqa: E731
    r3 = lambda f: [int(p == _r3(f)) for p in pats]  # noqa: E731
    return {split: {"model": pattern_metrics(s, model), "baseline_rule_R3": pattern_metrics(s, r3)}
            for split, s in (("heldout", held), ("e_cases", data.gt_flag_sets("E")))}


def flag_metrics(pred, true, crit) -> dict:
    ci = [i for i, c in enumerate(crit) if c]
    return {"accuracy": wilson(sum(p == t for p, t in zip(pred, true)), len(true)),
            "critical_recall": wilson(sum(pred[i] == true[i] for i in ci), len(ci)),
            "macro_f1": round(f1_score(true, pred, average="macro", zero_division=0), 4)}


def eval_flags() -> dict:
    clf = load_model("flag_model")["clf"]
    _, held_ids = data.flag_test_split()
    rows = data.flag_rows(held_ids, 200, data.SEED + 1)
    pred = list(clf.predict([r[0] for r in rows]))
    out = {"heldout_tests": {"model": flag_metrics(pred, [r[1] for r in rows], [r[2] for r in rows]),
                             "rules_flag_engine": "labels are flag_engine output (1.0 by construction)"}}
    e = data.gt_flag_rows("E")
    true, crit = [r[1] for r in e], [r[2] for r in e]
    out["e_cases_vs_expected_flag"] = {
        "model": flag_metrics(list(clf.predict([r[0] for r in e])), true, crit),
        "rules_flag_engine": flag_metrics([r[3] for r in e], true, crit)}
    return out


if __name__ == "__main__":
    res = {"normalize_names": eval_names(), "pattern_model": eval_patterns(), "flag_model": eval_flags()}
    (ROOT / "evals" / "results_ml.json").write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=1))
