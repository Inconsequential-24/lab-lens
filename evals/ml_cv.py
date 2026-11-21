"""Grouped k-fold cross-validation of the ML nodes, separate from evals/ml_eval.py.

Usage: .venv/bin/python evals/ml_cv.py [--k 5] [--seed 1234] [--out evals/results_ml_cv.json]

Retrains fresh models in memory (models/ is never touched). For every fold it reports TRAIN
(resubstitution) and TEST (held-out fold) metrics; afterwards one model per kind is fit on all
non-eval data and scored once on the frozen E* data, mirroring evals/ml_eval.py.

Groupings (chosen so nothing that identifies a test item is seen in training):
- names / by_test_id: GroupKFold, group = test_id; each unknown name (and its variants) is its own
  group labelled None. Held-out tests are absent from the model's vocabulary, so the correct
  answer for every TEST-fold item is abstain (open-set check); wrong-mapping is the key metric.
- names / by_rule: each generation rule is held out once (originals and D* names always train).
- patterns: group = exact flag vector, so identical inputs never sit in both train and test.
  Grouping by planted package was rejected: the held-out package would have no positives in
  training, which only measures that a tree cannot predict an unseen class.
- flags: group = test_id, so held-out tests have unseen reference ranges and scales.
Thresholds/margins are tuned on an inner group split of the TRAIN folds only.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

from sklearn.model_selection import GroupKFold
from sklearn.tree import DecisionTreeClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "evals"))

from lablens import reference  # noqa: E402
from lablens.ml import data  # noqa: E402
from lablens.ml.normalize_names import dictionary_lookup, scores  # noqa: E402
from ml_eval import _r3, flag_metrics, name_metrics, pattern_metrics, wilson  # noqa: E402
from train_ml import fit_names  # noqa: E402

GRID = [(th / 100, mg / 100) for th in range(50, 96, 2) for mg in range(0, 31, 2)]
ALL_RULES = data.TRAIN_RULES + data.HELDOUT_RULES
FIXED_TRAIN = ("orig", "gt_D")  # rule tags never held out in the by_rule grouping


# ---------------------------------------------------------------- generic helpers
def _assert_no_eval(items) -> None:
    """E* data must never enter a fold, tuning or training. Every pooled item carries a source tag."""
    bad = [it for it in items if it.get("source") == "E"]
    assert not bad, f"E* data leaked into CV pool: {bad[:3]}"


def _folds(groups: list, k: int):
    n = len(set(groups))
    gkf = GroupKFold(n_splits=min(k, n))
    return list(gkf.split(list(range(len(groups))), groups=groups))


def _summ(vals) -> dict:
    vals = [v for v in vals if v is not None]
    if not vals:
        return {"mean": None, "std": None}
    return {"mean": round(statistics.fmean(vals), 4),
            "std": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0}


def _aggregate(folds: list[dict], split: str) -> dict:
    """mean ± std of rates across folds plus pooled Wilson intervals over raw counts."""
    out = {}
    for sysname in folds[0][split]:
        agg = {}
        for metric, v in folds[0][split][sysname].items():
            rows = [f[split][sysname][metric] for f in folds]
            if isinstance(v, dict):
                agg[metric] = _summ(r["rate"] for r in rows) | {
                    "pooled": wilson(sum(r["k"] for r in rows), sum(r["n"] for r in rows))}
            elif isinstance(v, (int, float)):
                agg[metric] = _summ(rows)
        out[sysname] = agg
    return out


# ---------------------------------------------------------------- names
def name_pool(seed: int = data.SEED, n_var: int = 3) -> list[dict]:
    """Every alias with every rule (n_var variants each), D* names and unknown names (label None)."""
    rng = random.Random(seed)
    pool = []
    for tid, t in reference.load_tests().items():
        for n in data._aliases(t):
            pool.append({"name": n, "tid": tid, "rule": "orig", "group": tid, "source": "panels"})
            for rule in ALL_RULES:
                for _ in range(n_var):
                    pool.append({"name": data.variant(n, rule, rng, tid, t.get("method")), "tid": tid,
                                 "rule": rule, "group": tid, "source": "panels"})
    pool += [{"name": n, "tid": tid, "rule": "gt_D", "group": tid, "source": "D"} for n, tid in data.gt_names("D")]
    for u in data.UNKNOWN_NAMES:
        pool.append({"name": u, "tid": None, "rule": "orig", "group": f"unk:{u}", "source": "unknown"})
        for rule in ALL_RULES:
            pool.append({"name": data.variant(u, rule, rng, "", None), "tid": None, "rule": rule,
                         "group": f"unk:{u}", "source": "unknown"})
    seen, out = set(), []
    for it in pool:  # dedupe by exact (name, label); first occurrence decides rule/group
        key = (it["name"], it["tid"])
        if key not in seen:
            seen.add(key)
            out.append(it)
    _assert_no_eval(out)
    return out


def _tune(m: dict, dev: list[tuple[str, str | None]]) -> tuple[float, float]:
    """Same objective as scripts/train_ml.py: zero wrong mappings first, then max accuracy."""
    sc = [(scores(n, m), t) for n, t in dev]

    def rank(g):
        got = [tid if s >= g[0] and mg >= g[1] else None for (tid, s, mg), _ in sc]
        wrong = sum(p is not None and p != t for p, (_, t) in zip(got, sc))
        return (wrong, -sum(p == t for p, (_, t) in zip(got, sc)), g)
    return min(rank(g) for g in GRID)[2]


def fit_tuned_names(train: list[dict], seed: int, group_key: str = "group") -> dict:
    """Inner split of the TRAIN items only (~20% of groups) for tuning, then refit on all known train."""
    rng = random.Random(seed)
    groups = sorted({str(it[group_key]) for it in train})
    dev_g = set(rng.sample(groups, max(1, len(groups) // 5)))
    inner_tr = [(it["name"], it["tid"]) for it in train if str(it[group_key]) not in dev_g and it["tid"]]
    inner_dev = [(it["name"], it["tid"]) for it in train if str(it[group_key]) in dev_g]
    inner_dev += [(it["name"], None) for it in train if it["tid"] is None and str(it[group_key]) not in dev_g]
    labels = {t for _, t in inner_tr}
    inner_dev = [(n, t if t in labels else None) for n, t in inner_dev]  # unseen test -> abstain
    th, mg = _tune(fit_names(inner_tr), inner_dev)
    return fit_names([(it["name"], it["tid"]) for it in train if it["tid"]]) | {"threshold": th, "margin": mg}


def _name_fn(m):
    def f(s):
        if not s or not s.strip():
            return None
        tid, sim, mg = scores(s, m)
        return tid if sim >= m["threshold"] and mg >= m["margin"] else None
    return f


def _name_fold(train: list[dict], test: list[dict], seed: int, group_key: str) -> dict:
    m = fit_tuned_names(train, seed, group_key)
    known = set(m["labels"])
    dct = {data.norm(it["name"]): it["tid"] for it in train if it["tid"]}
    tr = [(it["name"], it["tid"]) for it in train]
    te = [(it["name"], it["tid"] if it["tid"] in known else None) for it in test]
    model, base = _name_fn(m), (lambda s: dictionary_lookup(s, dct))
    return {"n_train": len(train), "n_test": len(test), "threshold": m["threshold"], "margin": m["margin"],
            "train": {"model": name_metrics(tr, model)},
            "test": {"model": name_metrics(te, model), "baseline_dict_train_fold": name_metrics(te, base)}}


def cv_names(k: int = 5, seed: int = data.SEED, n_var: int = 3) -> dict:
    pool = name_pool(seed, n_var)
    out = {}
    # by_test_id: GroupKFold over test_id (unknowns are their own groups)
    groups = [it["group"] for it in pool]
    folds = []
    for i, (tr_i, te_i) in enumerate(_folds(groups, k)):
        tr, te = [pool[j] for j in tr_i], [pool[j] for j in te_i]
        assert not {it["group"] for it in tr} & {it["group"] for it in te}
        folds.append(_name_fold(tr, te, seed + i, "group") | {"held_out_groups": sorted({str(it["group"]) for it in te})})
    out["by_test_id"] = {"grouping": "GroupKFold, group = test_id; unknown names one group each (label None); "
                                     "held-out tests are out of vocabulary so expected answer = abstain",
                         "folds": folds, "train": _aggregate(folds, "train"), "test": _aggregate(folds, "test")}
    # by_rule: each generation rule held out once; originals and D* names always in train
    folds = []
    for i, rule in enumerate(ALL_RULES):
        tr = [it for it in pool if it["rule"] != rule]
        te = [it for it in pool if it["rule"] == rule]
        folds.append(_name_fold(tr, te, seed + i, "rule") | {"held_out_groups": [rule]})
    out["by_rule"] = {"grouping": f"leave-one-rule-out over {list(ALL_RULES)}; {list(FIXED_TRAIN)} always train",
                      "folds": folds, "train": _aggregate(folds, "train"), "test": _aggregate(folds, "test")}
    return out


def eval_names(seed: int = data.SEED, n_var: int = 3) -> dict:
    """Fit on all non-eval data; score once on E* printed names + held-out unknowns (as ml_eval.py)."""
    dev_unk = {x for x, t in data.name_splits()["dev"] if t is None}
    pool = [it for it in name_pool(seed, n_var) if it["tid"] or it["group"][4:] in dev_unk]
    m = fit_tuned_names(pool, seed, "group")
    e_names = data.gt_names("E") + [(u, None) for u in data.UNKNOWN_NAMES if u not in dev_unk]
    assert not {u for u, t in e_names if t is None} & {it["name"] for it in pool}, "eval unknowns leaked"
    model = _name_fn(m)
    return {"n_train_pool": len(pool), "threshold": m["threshold"], "margin": m["margin"],
            "e_exact_strings_also_in_pool": len({n for n, _ in data.gt_names("E")} & {it["name"] for it in pool}),
            "model": name_metrics(e_names, model),
            "hybrid_dict_then_model": name_metrics(e_names, lambda s: dictionary_lookup(s) or model(s)),
            "baseline_dict_all_panels": name_metrics(e_names, dictionary_lookup)}


# ---------------------------------------------------------------- patterns
def _pattern_preds(clf, sets):
    preds = [[int(x) for x in row] for row in clf.predict([data.flag_vector(f) for f in sets])]
    lut = {id(f): p for f, p in zip(sets, preds)}
    return lambda f: lut[id(f)]


def _fit_patterns(sets, seed):
    return DecisionTreeClassifier(random_state=seed, max_depth=8).fit(
        [data.flag_vector(f) for f in sets], [data.pattern_labels(f) for f in sets])


def cv_patterns(k: int = 5, seed: int = data.SEED, n_sets: int = 4000) -> dict:
    sets = data.synth_flag_sets(n_sets, seed) + data.gt_flag_sets("D")
    groups = [json.dumps(data.flag_vector(f)) for f in sets]
    pats = list(reference.load_packages())
    r3 = lambda f: [int(p == _r3(f)) for p in pats]  # noqa: E731
    folds = []
    for tr_i, te_i in _folds(groups, k):
        tr, te = [sets[j] for j in tr_i], [sets[j] for j in te_i]
        assert not {groups[j] for j in tr_i} & {groups[j] for j in te_i}
        clf = _fit_patterns(tr, seed)
        folds.append({"n_train": len(tr), "n_test": len(te),
                      "train": {"model": pattern_metrics(tr, _pattern_preds(clf, tr))},
                      "test": {"model": pattern_metrics(te, _pattern_preds(clf, te)),
                               "baseline_rule_R3": pattern_metrics(te, r3)}})
    return {"grouping": "GroupKFold, group = exact flag vector (no duplicate input in train and test)",
            "n_groups": len(set(groups)), "folds": folds,
            "train": _aggregate(folds, "train"), "test": _aggregate(folds, "test")}


def eval_patterns(seed: int = data.SEED, n_sets: int = 4000) -> dict:
    clf = _fit_patterns(data.synth_flag_sets(n_sets, seed) + data.gt_flag_sets("D"), seed)
    e = data.gt_flag_sets("E")
    pats = list(reference.load_packages())
    return {"model": pattern_metrics(e, _pattern_preds(clf, e)),
            "baseline_rule_R3": pattern_metrics(e, lambda f: [int(p == _r3(f)) for p in pats])}


# ---------------------------------------------------------------- flags
def flag_pool(seed: int, n_per: int) -> tuple[list, list[str]]:
    ids = [t for t, v in reference.load_tests().items() if v.get("ref")]
    rows, groups = [], []
    for tid in ids:  # per-test generation keeps the test_id group label exact
        r = data.flag_rows([tid], n_per, seed)
        rows += r
        groups += [tid] * len(r)
    return rows, groups


def _fit_flags(rows, seed):
    return DecisionTreeClassifier(random_state=seed, max_depth=10).fit([r[0] for r in rows], [r[1] for r in rows])


def cv_flags(k: int = 5, seed: int = data.SEED, n_per: int = 200) -> dict:
    rows, groups = flag_pool(seed, n_per)
    folds = []
    for tr_i, te_i in _folds(groups, k):
        tr, te = [rows[j] for j in tr_i], [rows[j] for j in te_i]
        assert not {groups[j] for j in tr_i} & {groups[j] for j in te_i}
        clf = _fit_flags(tr, seed)
        res = {}
        for name, part in (("train", tr), ("test", te)):
            true, crit = [r[1] for r in part], [r[2] for r in part]
            res[name] = {"model": flag_metrics(list(clf.predict([r[0] for r in part])), true, crit)}
        res["test"]["rules_flag_engine"] = flag_metrics([r[1] for r in te], [r[1] for r in te], [r[2] for r in te])
        folds.append({"n_train": len(tr), "n_test": len(te),
                      "held_out_groups": sorted({groups[j] for j in te_i})} | res)
    return {"grouping": "GroupKFold, group = test_id (unseen reference ranges/scales in the test fold); "
                        "rules_flag_engine is 1.0 by construction because labels are flag_engine output",
            "folds": folds, "train": _aggregate(folds, "train"), "test": _aggregate(folds, "test")}


def eval_flags(seed: int = data.SEED, n_per: int = 200) -> dict:
    clf = _fit_flags(flag_pool(seed, n_per)[0], seed)
    e = data.gt_flag_rows("E")
    true, crit = [r[1] for r in e], [r[2] for r in e]
    return {"model": flag_metrics(list(clf.predict([r[0] for r in e])), true, crit),
            "rules_flag_engine": flag_metrics([r[3] for r in e], true, crit)}


# ---------------------------------------------------------------- main
def run(k: int = 5, seed: int = data.SEED, n_var: int = 3, n_sets: int = 4000, n_per: int = 200) -> dict:
    return {
        "config": {"k": k, "seed": seed, "n_var": n_var, "n_sets": n_sets, "n_per": n_per,
                   "note": "separate from evals/results_ml.json; models retrained in memory; "
                           "E* data used only in the eval sections"},
        "normalize_names": {"cv": cv_names(k, seed, n_var), "eval": eval_names(seed, n_var)},
        "pattern_model": {"cv": cv_patterns(k, seed, n_sets), "eval": eval_patterns(seed, n_sets)},
        "flag_model": {"cv": cv_flags(k, seed, n_per), "eval": eval_flags(seed, n_per)},
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Grouped k-fold CV of the ML nodes.")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--seed", type=int, default=data.SEED)
    ap.add_argument("--out", type=Path, default=ROOT / "evals" / "results_ml_cv.json")
    a = ap.parse_args()
    if a.k < 2:
        ap.error("--k must be >= 2")
    t0 = time.perf_counter()
    res = run(a.k, a.seed)
    a.out.write_text(json.dumps(res, indent=2) + "\n")
    print(f"wrote {a.out} in {time.perf_counter() - t0:.1f}s")
