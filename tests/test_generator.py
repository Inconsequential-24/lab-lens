"""Checks for the synthetic report generator and its ground truth."""

import hashlib
import json
import math
from pathlib import Path

import pytest
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]

import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import generate_reports as gen  # noqa: E402


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    index = gen.generate(out)
    return out, index


def load_truth(out: Path, case_id: str) -> dict:
    return json.loads((out / "ground_truth" / f"{case_id}.json").read_text(encoding="utf-8"))


def pdf_text(out: Path, truth: dict) -> str:
    rel = truth["source_pdf"].removeprefix("data/")
    reader = PdfReader(out / rel)
    return "\n".join(page.extract_text() for page in reader.pages)


def test_fifteen_sources_and_thirty_eval_cases(generated):
    out, index = generated
    assert sum(c["split"] == "source" for c in index) == 15
    assert sum(c["split"] == "eval" for c in index) == 30
    listed = json.loads((out / "ground_truth" / "index.json").read_text(encoding="utf-8"))
    assert len(listed["sources"]) == 15 and len(listed["eval_cases"]) == 30


def test_every_eval_case_links_to_a_source(generated):
    out, index = generated
    sources = {c["id"] for c in index if c["split"] == "source"}
    evals = [c for c in index if c["split"] == "eval"]
    for case in evals:
        assert case["source"] in sources, case["id"]
        truth = load_truth(out, case["id"])
        assert (truth["source"], truth["variation"]) == (case["source"], case["variation"])
        assert truth["change"]
    counts = {v: sum(c["variation"] == v for c in evals) for v in gen.VARIATION_COUNTS}
    assert counts == {"controlled_variation": 10, "perturbation": 8,
                      "extraction_challenge": 6, "adversarial": 6}
    for src in sources:
        assert 1 <= sum(c["source"] == src for c in evals) <= 3, src


def test_eval_cases_inherit_from_their_source():
    specs = gen.load_yaml(ROOT / "data" / "case_specs.yaml")["cases"]
    resolved = {c["id"]: c for c in gen.resolve_cases(specs)}
    # E15 overrides only the layout, so it keeps D04's panels, sex, age and values.
    e15, d04 = resolved["E15"], resolved["D04"]
    assert e15["layout"] != d04["layout"]
    assert (e15["panels"], e15["sex"], e15["age"], e15["values"]) == \
        (d04["panels"], d04["sex"], d04["age"], d04["values"])
    # A null value removes an inherited key.
    assert "MCV" not in resolved["E25"]["values"] and resolved["E25"]["values"]["HB"] == "6.2"


def test_controlled_variations_change_the_outcome(generated):
    out, index = generated
    for case in index:
        if case.get("variation") != "controlled_variation":
            continue
        truth, source = load_truth(out, case["id"]), load_truth(out, case["source"])

        def signature(t):
            return (t["expected"]["next_step"], t["expected"]["rule"],
                    sorted((r["test_id"], r["expected_flag"], r["expected_severity"])
                           for r in t["tests"] if r["expected_flag"] != "normal"))
        assert signature(truth) != signature(source), case["id"]


def test_duplicate_eval_case_is_rejected():
    entry = {"id": "E99", "split": "eval", "source": "D01", "fingerprint": "abc", "file_hashes": ["h1"]}
    source = {"id": "D01", "split": "source", "source": None, "fingerprint": "abc", "file_hashes": ["h2"]}
    copy_ = {"id": "E98", "split": "eval", "source": "D02", "fingerprint": "xyz", "file_hashes": ["h1"]}
    problems = gen.find_duplicates([entry, source, copy_])
    assert any("E99" in p and "D01" in p for p in problems)
    assert any("E99" in p and "E98" in p and "file" in p for p in problems)
    assert gen.find_duplicates([{**entry, "fingerprint": "new", "file_hashes": ["h3"]}, source]) == []


def test_no_eval_case_duplicates_a_source_or_another_case(generated):
    out, index = generated
    hashes = {}
    for path in (out / "reports").rglob("*"):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest not in hashes, f"{path.name} identical to {hashes[digest]}"
            hashes[digest] = path.name


def test_all_outcomes_and_rules_are_covered(generated):
    _, index = generated
    assert {c["next_step"] for c in index} == {"no_action", "doctor_consult", "follow_up_test_package"}
    assert {c["rule"] for c in index} >= {"R1_critical", "R2_marked", "R3_package", "R4_mild",
                                          "R4_printed_flag", "R5_verify", "R6_normal"}
    assert {p for c in index for p in c["panels"]} == {"cbc", "lipid", "hba1c", "thyroid", "lft"}


def test_every_ground_truth_field_is_printed_on_the_page(generated):
    out, index = generated
    for case in index:
        truth = load_truth(out, case["id"])
        text = pdf_text(out, truth)
        for test in truth["tests"]:
            for field in (test["printed_name"], test["value"]["raw"], test["unit_raw"]):
                assert field in text, f"{case['id']} {test['test_id']}: {field!r} not in PDF text"
            if test["ref"]["raw"]:
                assert test["ref"]["raw"] in text, f"{case['id']} {test['test_id']}: range missing"
        for name in truth["unrecognised_tests"]:
            assert name in text
        for remark in truth["lab_remarks"]:
            assert remark in text


def test_derived_values_are_consistent(generated):
    out, index = generated
    for case in index:
        values = {t["test_id"]: t["value"]["number"] for t in load_truth(out, case["id"])["tests"]}
        if "VLDL" in values:
            assert math.isclose(values["VLDL"], values["TG"] / 5, abs_tol=0.05)
            assert math.isclose(values["NONHDL"], values["TC"] - values["HDL"], abs_tol=0.5)
        if "GLOB" in values:
            assert math.isclose(values["GLOB"], values["TP"] - values["ALB"], abs_tol=0.006)
        if "NEUT" in values:
            diff = sum(values[k] for k in ("NEUT", "LYMPH", "MONO", "EOS", "BASO"))
            assert diff == 100, f"{case['id']}: differential sums to {diff}"


def test_critical_cases_are_marked_critical(generated):
    out, index = generated
    for case in index:
        truth = load_truth(out, case["id"])
        has_critical = any(t["is_critical"] for t in truth["tests"])
        assert has_critical == (truth["expected"]["urgency"] == "urgent"), case["id"]


def test_values_stay_within_plausible_limits(generated):
    out, index = generated
    tests = gen.load_yaml(ROOT / "reference" / "panels.yaml")["tests"]
    for case in index:
        for t in load_truth(out, case["id"])["tests"]:
            low, high = tests[t["test_id"]]["plausible"]
            assert low <= t["value_canonical"] <= high, f"{case['id']} {t['test_id']}"


def test_image_cases_have_an_image_input(generated):
    out, index = generated
    for case in index:
        if case["input_type"] == "image":
            assert (out / case["input"].removeprefix("data/")).exists()
            assert load_truth(out, case["id"])["pages"] == 1


def test_generation_is_deterministic(generated, tmp_path):
    out, _ = generated
    gen.generate(tmp_path)

    def digest(root: Path) -> dict:
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob("*")) if p.is_file()}

    assert digest(out) == digest(tmp_path)


@pytest.mark.parametrize("value,comp,low,high,expected", [
    (5.0, "=", 4.0, 5.6, "normal"),
    (5.6, "=", 4.0, 5.6, "normal"),          # bounds are inclusive
    (5.7, "=", 4.0, 5.6, "high"),
    (0.01, "<", 0.27, 4.2, "low"),           # "<0.01" against a low bound
    (0.10, "<", None, 0.20, "normal"),       # "<0.10" against "< 0.20"
    (0.5, "<", 0.3, 1.2, "unknown"),         # undecidable
    (12.0, "=", None, None, "unknown"),      # no range
])
def test_expected_flag(value, comp, low, high, expected):
    assert gen.expected_flag(value, comp, low, high) == expected


def test_zero_bound_does_not_divide_by_zero():
    # Below a lower bound of 0 with an upper bound: deviation relative to the range width.
    assert gen.expected_severity("low", -1.0, "=", 0.0, 40.0, None) == ("mild", False)
    # Below a lower bound of 0 with no upper bound: no scale to compare against, so marked.
    assert gen.expected_severity("low", -1.0, "=", 0.0, None, None) == ("marked", False)


def test_all_four_layouts_are_used(generated):
    _, index = generated
    counts = {layout: sum(c["layout"] == layout for c in index) for layout in "ABCD"}
    assert all(n >= 6 for n in counts.values()), counts


def test_row_pages_match_page_count(generated):
    out, index = generated
    for case in index:
        truth = load_truth(out, case["id"])
        pages = {t["page"] for t in truth["tests"]}
        assert max(pages) <= truth["pages"], case["id"]
    e12 = load_truth(out, "E12")
    assert e12["pages"] >= 2 and len({t["page"] for t in e12["tests"]}) >= 2


def test_layout_d_prints_unitless_ratio_and_lab_ranges(generated):
    out, _ = generated
    tests = {t["test_id"]: t for t in load_truth(out, "D13")["tests"]}
    assert tests["AST_ALT"]["unit_raw"] == "" and tests["AST_ALT"]["ref"]["raw"] == "<1.00"
    assert tests["GGT"]["ref"]["raw"] == "0 - 55" and tests["GGT"]["ref"]["low"] == 0.0
    d06 = {t["test_id"]: t for t in load_truth(out, "D06")["tests"]}
    assert d06["LDL_HDL"]["ref"]["raw"] == "Desirable : 1.5-3.5"
    assert (d06["LDL_HDL"]["ref"]["low"], d06["LDL_HDL"]["ref"]["high"]) == (1.5, 3.5)


def test_layout_d_reports_are_flagged_as_naming_conditions(generated):
    out, index = generated
    for case in index:
        truth = load_truth(out, case["id"])
        if case["layout"] == "D":
            assert truth["prints_condition_names"] and truth["has_promotional_text"]
            assert truth["expected"]["must_not_include"], case["id"]


@pytest.mark.parametrize("raw,expected", [
    ("0 - 38", (0.0, 38.0)), ("0-0.5", (0.0, 0.5)), ("<0.30", (None, 0.30)), (">40", (40.0, None)),
    ("Desirable : 1.5-3.5", (1.5, 3.5)), ("30.00 - 120.00", (30.0, 120.0)), ("", (None, None)),
])
def test_parse_range_raw(raw, expected):
    assert gen.parse_range_raw(raw) == expected
