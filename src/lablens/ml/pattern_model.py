"""pattern_model (ML) node: co-occurring abnormal results, worded neutrally (PLAN.md section 8).

Output never names a condition, only test IDs: "these results are outside range together: ...".
"""
from __future__ import annotations

from lablens import reference
from lablens.ml import load_model
from lablens.ml.data import flag_vector
from lablens.schemas import FlaggedTest

PHRASE = "these results are outside range together: "


def detect(flags: dict[str, str], model=None) -> list[str]:
    """Pattern ids (package keys) predicted present for a test_id -> flag mapping."""
    m = model or load_model("pattern_model")
    pred = m["clf"].predict([flag_vector(flags)])[0]
    return [pid for pid, hit in zip(m["patterns"], pred) if hit]


def pattern_model(tests: list[FlaggedTest]) -> list[str]:
    """Function node: neutral pattern strings for the doctor note."""
    flags = {t.test_id: t.flag.value for t in tests if t.test_id}
    pkgs = reference.load_packages()
    out = []
    for pid in detect(flags):
        ids = [t for t in pkgs[pid]["allowed_abnormal"] if flags.get(t) in ("low", "high")]
        if len(ids) >= 1:
            out.append(PHRASE + ", ".join(ids))
    return out
