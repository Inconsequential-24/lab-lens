import re

import pytest

from lablens import reference
from lablens.ml import data, load_model
from lablens.ml.normalize_names import normalize_name, predict
from lablens.ml.pattern_model import PHRASE, detect, pattern_model
from lablens.schemas import Flag, FlaggedTest, RefRange, Severity, Value

CONDITION = re.compile(r"an(a)?emi|diabet|thyroid|hepat|liver|deficien|lipid|disease|syndrome", re.I)


def test_loader_caches_models():
    assert load_model("normalize_names") is load_model("normalize_names")
    assert {"clf", "patterns"} <= set(load_model("pattern_model"))


@pytest.mark.parametrize("tid", list(reference.load_tests()))
def test_canonical_names_map(tid):
    assert predict(reference.load_tests()[tid]["name"])[0] == tid
    assert normalize_name(reference.load_tests()[tid]["name"].upper()) == tid


@pytest.mark.parametrize("name", ["Vitamin B12", "Serum Ferritin", "Free T4", "Creatinine",
                                  "Urine Routine", "", "   ", "xyzzy"])
def test_unknown_names_abstain(name):
    assert normalize_name(name) is None


def test_name_splits_disjoint_and_deterministic():
    sp = data.name_splits()
    train = {n for n, _ in sp["train"] + sp["dev"]}
    assert not train & {n for n, _ in sp["heldout"]}
    assert data.name_splits() == sp  # deterministic


def _ft(tid, flag):
    return FlaggedTest(raw_name=tid, test_id=tid, panel=None, value=Value(raw="1", number=1.0),
                       unit_raw=None, unit=None, ref=RefRange(raw="", low=None, high=None, source="none"),
                       printed_flag=None, remark=None, page=1, source_span="", flag=Flag(flag),
                       severity=Severity.MILD, is_critical=False,
                       flag_disagrees_with_printed=False, confidence=1.0)


def test_pattern_output_neutral_and_matches_package():
    out = pattern_model([_ft("HB", "low"), _ft("MCV", "low"), _ft("MCH", "low"), _ft("TSH", "normal")])
    assert out == [PHRASE + "HB, MCV, MCH"]
    assert detect({"HB": "low", "MCV": "low"}) == ["iron_studies_package"]
    for flags in data.synth_flag_sets(200, 7):
        for s in pattern_model([_ft(t, f) for t, f in flags.items()]):
            assert s.startswith(PHRASE) and not CONDITION.search(s)


def test_pattern_and_flag_splits_disjoint():
    seen = {tuple(data.flag_vector(f)) for f in data.synth_flag_sets(4000, data.SEED)}
    assert seen  # held-out vectors are filtered against this set in evals/ml_eval.py
    tr, held = data.flag_test_split()
    assert held and not set(tr) & set(held)


def test_model_mapped_names_are_reported_for_verification():
    from lablens.ml.normalize_names import normalize_name_with_source
    assert normalize_name_with_source("Haemoglobin") == ("HB", "dictionary")
    assert normalize_name_with_source("Thyroid Stimulating Hormone (TSH)") == ("TSH", "model")
    assert normalize_name_with_source("Bleeding Time") == (None, None)


def test_load_model_verifies_sha256(tmp_path):
    import json
    import shutil
    from lablens.ml import MODELS_DIR, file_sha256
    for name in ("normalize_names", "pattern_model", "flag_model"):
        card = json.loads((MODELS_DIR / f"{name}.card.json").read_text())
        assert card["sha256"] == file_sha256(MODELS_DIR / f"{name}.joblib")
    shutil.copy(MODELS_DIR / "flag_model.joblib", tmp_path / "flag_model.joblib")
    (tmp_path / "flag_model.card.json").write_text(json.dumps({"sha256": "0" * 64}))
    with pytest.raises(ValueError):
        load_model("flag_model", str(tmp_path))
    (tmp_path / "flag_model.card.json").write_text("{}")
    with pytest.raises(ValueError):
        load_model.__wrapped__("flag_model", str(tmp_path))


def test_train_script_help_does_not_train():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "scripts/train_ml.py", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "--out" in r.stdout and "saved to" not in r.stdout
