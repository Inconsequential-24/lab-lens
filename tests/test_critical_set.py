"""Held-out critical-value set: generator determinism, counts, R1 routing, never used for tuning."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_critical_set as gcs  # noqa: E402
from lablens.decision import route_next_step  # noqa: E402
from lablens.flag_engine import flag_test  # noqa: E402
from lablens.schemas import ExtractedTest  # noqa: E402

EXPECTED_COUNTS = {"boundary_alt_unit": 50, "boundary_canonical": 45, "comparator_control": 18,
                   "comparator_critical": 22, "control_abnormal_noncritical": 18,
                   "control_no_critical_limit": 10, "control_normal": 18, "misleading_printed_range": 35,
                   "no_or_normal_printed_flag": 36, "no_printed_range": 18, "unit_equivalent_spelling": 42}


def _rows(tmp_path):
    gcs.generate(tmp_path, pdfs=False)
    return json.loads((tmp_path / "rows.json").read_text(encoding="utf-8"))


def test_generator_is_deterministic_and_matches_committed_rows(tmp_path):
    a = (_rows(tmp_path / "a"))
    b = (_rows(tmp_path / "b"))
    assert a == b
    committed = json.loads((ROOT / "data" / "critical_set" / "rows.json").read_text(encoding="utf-8"))
    assert committed["rows"] == a["rows"]


def test_counts_per_category(tmp_path):
    d = _rows(tmp_path)
    assert d["counts_by_category"] == EXPECTED_COUNTS
    assert d["n_rows"] == sum(EXPECTED_COUNTS.values()) and d["n_critical"] == 196


def test_every_critical_row_routes_r1_and_controls_do_not(tmp_path):
    for row in _rows(tmp_path)["rows"]:
        ft = flag_test(ExtractedTest(**row["test"]))
        rule = route_next_step([ft]).rule_id
        assert ft.is_critical is row["expected_is_critical"], row["id"]
        assert (rule == "R1_critical") is row["expected_is_critical"], row["id"]


def test_set_is_not_referenced_by_tuning_code():
    allowed = {ROOT / "scripts" / "generate_critical_set.py", ROOT / "evals" / "critical_eval.py",
               Path(__file__).resolve()}
    offenders = []
    for folder in ("src", "scripts", "evals", "tests", "models", "reference"):
        for p in (ROOT / folder).rglob("*"):
            if p.is_file() and p.suffix in {".py", ".yaml", ".yml", ".json", ".txt", ".md"} \
                    and p.resolve() not in allowed and p.name != "results_critical.json":
                text = p.read_text(encoding="utf-8", errors="ignore")
                if "critical_set" in text or "results_critical" in text:
                    offenders.append(str(p.relative_to(ROOT)))
    assert offenders == []
