import json
from pathlib import Path

import pytest

from lablens.decision import route_next_step
from lablens.flag_engine import flag_tests
from lablens.safety import safety_check
from lablens.schemas import ExtractedTest, RefRange, Value
from lablens.templates import DISCLAIMER, template_fallback, urgent_template

GT = Path(__file__).resolve().parents[1] / "data" / "ground_truth"
D_CASES = sorted(p.stem for p in GT.glob("D*.json"))


def make(test_id, raw, number, low, high, unit="g/dL", confidence=1.0, ref_raw=None):
    return ExtractedTest(raw_name=test_id, test_id=test_id, panel=None,
                         value=Value(raw=raw, number=number), unit_raw=unit, unit=unit,
                         ref=RefRange(raw=ref_raw or f"{low} - {high}", low=low, high=high,
                                      source="report"),
                         printed_flag=None, remark=None, page=1, source_span="",
                         confidence=confidence)


def gt_tests(case):
    data = json.loads((GT / f"{case}.json").read_text(encoding="utf-8"))
    rows = [ExtractedTest(raw_name=t["printed_name"], test_id=t["test_id"], panel=t["panel"],
                          value=Value(**t["value"]), unit_raw=t["unit_raw"], unit=t["unit"],
                          ref=RefRange(**t["ref"]), printed_flag=t["printed_flag"],
                          remark=t.get("remark"), page=t["page"], source_span="",
                          confidence=1.0) for t in data["tests"]]
    return flag_tests(rows)


def run(tests):
    rec = route_next_step(tests)
    return template_fallback(tests, rec), rec


@pytest.mark.parametrize("case", D_CASES)
def test_fallback_passes_safety_for_ground_truth(case):
    tests = gt_tests(case)
    exps, rec = run(tests)
    assert [e.language for e in exps] == ["en", "hi"]
    assert all(e.source == "template_fallback" and e.statements for e in exps)
    assert safety_check(exps, tests, rec) == []


def test_d_cases_present():
    assert len(D_CASES) == 15


def test_urgent_template_names_test_and_value_both_languages():
    tests = flag_tests([make("HB", "6.5", 6.5, 12.0, 15.0)])
    en, hi = urgent_template("en", tests), urgent_template("hi", tests)
    assert en.startswith("URGENT") and "Hemoglobin 6.5 g/dL" in en and "doctor" in en
    assert "Hemoglobin" in hi and "6.5 g/dL" in hi and "डॉक्टर" in hi
    exps, rec = run(tests)
    assert all(e.urgent_message for e in exps)
    assert safety_check(exps, tests, rec) == []


def test_urgent_low_confidence_adds_confirm():
    tests = flag_tests([make("HB", "6.5", 6.5, 12.0, 15.0, confidence=0.4)])
    assert "confirm this value with the lab" in urgent_template("en", tests)
    assert "पुष्टि" in urgent_template("hi", tests)


def test_no_urgent_without_critical():
    assert urgent_template("en", flag_tests([make("HB", "10.2", 10.2, 12.0, 15.0)])) is None


def test_example_response_shape():
    tests = flag_tests([make("HB", "10.2", 10.2, 12.0, 15.0), make("MCV", "85", 85, 80, 100, "fL")])
    exps, rec = run(tests)
    en = exps[0]
    assert en.statements[0].text == "Your Hemoglobin is 10.2 g/dL, below the range of 12 to 15 g/dL printed on your report."
    assert en.statements[1].cites[1].id == "HB.low"
    assert en.disclaimer == DISCLAIMER["en"]
    assert {s.claim_id for s in exps[0].statements} == {s.claim_id for s in exps[1].statements}
    assert safety_check(exps, tests, rec) == []


def test_all_normal_is_bounded():
    tests = flag_tests([make("HB", "13", 13, 12.0, 15.0)])
    exps, rec = run(tests)
    assert "within the ranges printed on your report" in exps[0].summary
    assert "healthy" not in exps[0].summary
    assert safety_check(exps, tests, rec) == []
