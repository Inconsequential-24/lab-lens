"""Offline tests for evals/run.py: stub extraction built from ground truth, template explanations."""
import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals import run as ev  # noqa: E402
from evals.ml_eval import wilson  # noqa: E402
from lablens.budget import BudgetGuard  # noqa: E402
from lablens.extract import NoOutput, Usage  # noqa: E402
from lablens.schemas import Extraction, ExtractedRow  # noqa: E402

CASES = ["E01", "E25"]  # controlled_variation (no critical) + adversarial (1 critical row)


async def no_live_explain(node, instr, msg, schema):
    raise NoOutput(Usage())


class GtStub:
    """Returns the ground-truth rows of whichever case the pipeline is processing."""
    def __init__(self):
        self.queue: list[str] = []

    async def __call__(self, doc, hint):
        gt = ev.load_gt(self.queue.pop(0)) if self.queue else self.last
        self.last = gt
        rows = [ExtractedRow(raw_name=t["printed_name"], value_raw=t["value"]["raw"], unit_raw=t["unit_raw"],
                             ref_raw=t["ref"]["raw"], ref_low=t["ref"]["low"], ref_high=t["ref"]["high"],
                             printed_flag=t["printed_flag"]) for t in gt["tests"]]
        return Extraction(tests=rows, report_date=gt["report_date"]), Usage(calls=1, tokens_in=1000, tokens_out=200)


def _run(tmp_path, guard_inr=None, max_inr=5.0):
    stub = GtStub()
    stub.queue = list(CASES)
    guard = BudgetGuard(tmp_path / "b.sqlite", guard_inr=guard_inr)
    return asyncio.run(ev.main(1, CASES, max_inr, tmp_path / "r.json", 0, guard=guard, caller=stub,
                               explain_caller=no_live_explain))


def _snapshot():
    h = hashlib.sha256()
    for d in ("data", "src/lablens/prompts"):
        for p in sorted((ROOT / d).rglob("*")):
            if p.is_file():
                h.update(str(p).encode() + p.read_bytes())
    return h.hexdigest()


def test_perfect_scores_groups_and_outputs(tmp_path):
    before = _snapshot()
    out = _run(tmp_path)
    assert _snapshot() == before  # nothing written back into data/ or prompts (no tuning on E*)
    p = out["aggregate"]["pooled"]
    for m in ("extraction_precision", "extraction_recall", "value_accuracy", "unit_accuracy",
              "range_accuracy", "name_accuracy", "flag_severity_accuracy_per_test",
              "flags_all_correct_per_report", "next_step_and_urgency_accuracy", "rule_accuracy"):
        assert p[m]["rate"] == 1.0, m
    assert p["critical_recall"]["k"] == p["critical_recall"]["n"] == 1
    assert p["unsafe_advice_rate"]["k"] == 0 and p["fallback_rate"]["k"] == 2
    g = out["aggregate"]["per_group_pooled"]
    assert g["controlled_variation"]["next_step_accuracy"]["n"] == 1
    assert g["adversarial"]["critical_recall"]["n"] == 1 and g["perturbation"]["next_step_accuracy"]["n"] == 0
    assert out["summary"]["runs_completed"] == 1 and out["summary"]["aborted"] is None
    assert out["aggregate"]["llm_judge"].startswith("not run")
    assert json.loads((tmp_path / "r.json").read_text())["summary"]["case_runs_scored"] == 2
    md = (tmp_path / "r.md").read_text()
    assert "100.0% (2 of 2" in md and "critical_recall" in md


def test_scoring_counts_errors():
    gt = ev.load_gt("E01")

    class R:  # minimal stand-in for a ReportResult with one wrong flag and one dropped row
        status, warnings, explanations = "partial", [], []

    from lablens.schemas import Recommendation
    tests = [dict(t) for t in gt["tests"][1:]]
    pred = {"tests": [{"test_id": t["test_id"], "raw_name": t["printed_name"], "value": t["value"],
                       "unit_raw": t["unit_raw"], "ref": t["ref"], "flag": t["expected_flag"],
                       "severity": t["expected_severity"], "is_critical": False} for t in tests],
            "unrecognised_tests": ["JUNK"], "low_confidence_tests": [], "status": "partial", "warnings": [],
            "metrics": {"tokens_in": 0, "tokens_out": 0, "cost_inr": 0}}
    pred["tests"][0]["flag"] = "high"
    r = R()
    r.model_dump = lambda mode=None: pred
    r.recommendation = Recommendation(next_step="no_action", package_id=None, urgency="none",
                                      reason_test_ids=[], rule_id="R6_normal")
    r.tests = []
    s = ev.score_case(gt, r)
    n = len(gt["tests"])
    assert s["tp"] == n - 1 and s["pred_rows"] == n and s["flag_ok"] == n - 2
    assert s["report_flags_ok"] == 0 and s["next_step_ok"] == 0 and s["withheld_reports"] == 1


def test_wilson_reused():
    w = wilson(2, 2)
    assert w["rate"] == 1.0 and 0.34 < w["ci95"][0] < 0.35 and w["ci95"][1] == 1.0
    assert wilson(0, 0)["rate"] is None


def test_budget_abort_recorded(tmp_path):
    out = _run(tmp_path, max_inr=1e-9)
    assert out["summary"]["aborted"]["case"] == "E01" and out["summary"]["case_runs_scored"] == 0
    assert (tmp_path / "r.md").exists()


def test_provider_outage_retried_then_excluded(tmp_path):
    from google.genai import errors

    calls = {"n": 0}

    async def down(doc, hint):
        calls["n"] += 1
        raise errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "busy"}})

    out = asyncio.run(ev.main(1, ["E01"], 5.0, tmp_path / "r.json", 0,
                              guard=BudgetGuard(tmp_path / "b.sqlite"), caller=down,
                              explain_caller=no_live_explain, backoff_scale=0))
    x = out["per_case_run"][0]
    assert x["status"] == "provider_unavailable" and x["attempts"] == 4
    ex = out["summary"]["excluded_provider_unavailable"]
    assert ex["total"] == 1 and ex["per_run"] == {1: 1} and out["summary"]["case_runs_scored"] == 0
    assert out["aggregate"]["pooled"]["next_step_accuracy"]["n"] == 0  # not in any denominator
    assert "Excluded (provider_unavailable" in (tmp_path / "r.md").read_text()
