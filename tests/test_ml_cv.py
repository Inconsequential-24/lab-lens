"""Grouped k-fold CV harness (evals/ml_cv.py): leakage, coverage, schema, determinism."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))

import ml_cv  # noqa: E402
from lablens.ml import data  # noqa: E402

SMALL = dict(k=3, n_var=1, n_sets=300, n_per=20)


@pytest.fixture(scope="module")
def res():
    return ml_cv.run(**SMALL)


def _e_names():
    return {n for n, _ in data.gt_names("E")}


def test_name_folds_disjoint_and_each_group_held_out_once():
    pool = ml_cv.name_pool(n_var=1)
    groups = [it["group"] for it in pool]
    seen = []
    for tr, te in ml_cv._folds(groups, 3):
        g_tr, g_te = {groups[i] for i in tr}, {groups[i] for i in te}
        assert not g_tr & g_te
        seen += sorted(g_te)
    assert sorted(seen) == sorted(set(groups))


def test_flag_and_pattern_folds_disjoint_and_complete():
    rows, groups = ml_cv.flag_pool(data.SEED, 5)
    held = []
    for tr, te in ml_cv._folds(groups, 3):
        assert not {groups[i] for i in tr} & {groups[i] for i in te}
        held += list({groups[i] for i in te})
    assert sorted(held) == sorted(set(groups))


def test_no_eval_data_in_pools():
    pool = ml_cv.name_pool(n_var=1)
    assert all(it["source"] != "E" for it in pool)
    sources = {it["source"] for it in pool}
    assert sources <= {"panels", "D", "unknown"}
    with pytest.raises(AssertionError):
        ml_cv._assert_no_eval([{"source": "E"}])
    # every flag-pool row is synthetic from panels.yaml ranges, never an E* row
    e_feats = {tuple(r[0]) for r in data.gt_flag_rows("E")}
    rows, _ = ml_cv.flag_pool(data.SEED, 5)
    assert not e_feats & {tuple(r[0]) for r in rows}


def test_eval_unknowns_never_in_train_pool():
    dev_unk = {x for x, t in data.name_splits()["dev"] if t is None}
    eval_unk = set(data.UNKNOWN_NAMES) - dev_unk
    assert eval_unk and not eval_unk & dev_unk


def test_schema_has_train_test_eval(res):
    nn = res["normalize_names"]
    for g in ("by_test_id", "by_rule"):
        cv = nn["cv"][g]
        assert {"train", "test", "folds"} <= set(cv)
        assert "baseline_dict_train_fold" in cv["test"]
        assert {"mean", "std", "pooled"} <= set(cv["test"]["model"]["wrong_mapping"])
    assert {"model", "baseline_dict_all_panels"} <= set(nn["eval"])
    assert len(nn["cv"]["by_rule"]["folds"]) == len(ml_cv.ALL_RULES)
    for m in ("pattern_model", "flag_model"):
        assert {"train", "test", "folds"} <= set(res[m]["cv"])
        assert "model" in res[m]["eval"]
    assert "critical_recall" in res["flag_model"]["cv"]["test"]["rules_flag_engine"]
    assert len(res["flag_model"]["cv"]["folds"]) == 3


def test_deterministic_given_seed(res):
    assert ml_cv.cv_patterns(3, data.SEED, 300) == res["pattern_model"]["cv"]
    assert ml_cv.cv_flags(3, data.SEED, 20) == res["flag_model"]["cv"]
    assert ml_cv.name_pool(data.SEED, 1) == ml_cv.name_pool(data.SEED, 1)
