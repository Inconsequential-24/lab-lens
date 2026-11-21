"""Explanation path (plan_statements -> render_en/render_hi -> safety_check), LLM stubbed."""
import asyncio
import json
import sqlite3

import pytest

from lablens import pipeline
from lablens.budget import BudgetGuard
from lablens.cache import ResponseCache
from lablens.explain import Plan, Rendered
from lablens.extract import Usage
from lablens.schemas import Extraction, ExtractedRow, FlaggedTest
from lablens.templates import _claims, _SUMMARY
from lablens.glossary import glossary_lookup


def rows(case):
    gt = json.load(open(f"data/ground_truth/{case}.json"))
    return [ExtractedRow(raw_name=t["printed_name"], value_raw=t["value"]["raw"],
                         unit_raw=t["unit_raw"], ref_raw=t["ref"]["raw"], ref_low=t["ref"]["low"],
                         ref_high=t["ref"]["high"], printed_flag=t["printed_flag"])
            for t in gt["tests"]]


class ExtractStub:
    def __init__(self, case, tokens_in=100):
        self.case, self.tokens_in = case, tokens_in

    async def __call__(self, doc, hint):
        return Extraction(tests=rows(self.case), report_date="2026-09-17"), \
            Usage(calls=1, tokens_in=self.tokens_in, tokens_out=50)


class LlmStub:
    """Answers like a well-behaved model, using the deterministic template text; `bad` maps a
    node name to how many of its first calls return a bad answer."""

    def __init__(self, bad=None):
        self.bad, self.calls = dict(bad or {}), []
        self.claims, self.urgent = None, False

    async def __call__(self, node, instr, msg, schema):
        self.calls.append(node)
        data = json.loads(msg.split(">\n", 1)[1].rsplit("\n</", 1)[0])
        bad = self.calls.count(node) <= self.bad.get(node, 0)
        u = Usage(calls=1, tokens_in=1000, tokens_out=200, tokens_thinking=10)
        if node == "plan_statements":
            return self._plan(bad), u
        lang = data["language"]
        stmts = [{"claim_id": c, "text": t[lang]} for c, t, _ in self.claims]
        if bad:  # banned phrase in this language only -> render-level failure
            stmts[0]["text"] += " You may have anemia." if lang == "en" else " यह एनीमिया है।"
        kind = "urgent" if "URGENT" in msg or self.urgent else "some"
        return Rendered(summary=_SUMMARY[kind][lang], statements=stmts), u

    def _plan(self, bad):
        cl = [{"claim_id": c, "content": t["en"], "cites": [x.model_dump() for x in cites]}
              for c, t, cites in self.claims]
        if bad:  # unknown citation -> plan-level failure
            cl[0]["cites"] = [{"kind": "test", "id": "NOT_A_TEST"}]
        return Plan.model_validate({"claims": cl})


def run(tmp_path, case, stub, guard_inr=None, real_upload=False, cache=None, extract_in=100):
    async def go():
        state = {}
        r = await pipeline.run(f"data/reports/source/{case}.pdf", caller=ExtractStub(case, extract_in),
                               explain_caller=stub, guard=BudgetGuard(
                                   tmp_path / "b.sqlite", guard_inr=guard_inr),
                               real_upload=real_upload, cache=cache, state_out=state)
        return r, state
    return asyncio.run(go())


def prime(stub, case, tmp_path):
    """Fill stub.claims from a fallback-only run of the same report."""
    async def nolive(*a):
        from lablens.extract import NoOutput
        raise NoOutput(Usage())
    r, _ = run(tmp_path, case, nolive)
    tests = [FlaggedTest.model_validate(t.model_dump()) for t in r.tests]
    stub.claims = _claims(tests, r.recommendation, glossary_lookup([t.test_id for t in tests]))
    stub.urgent = any(t.is_critical for t in tests)
    return stub


def test_happy_path_both_languages(tmp_path):
    stub = prime(LlmStub(), "D02", tmp_path)
    r, st = run(tmp_path, "D02", stub)
    assert sorted(stub.calls) == ["plan_statements", "render_en", "render_hi"]
    assert {e.language for e in r.explanations} == {"en", "hi"}
    assert all(e.source == "llm" for e in r.explanations)
    assert r.status == "complete" and r.metrics.retries == 0
    assert {"plan_statements", "render_en", "render_hi", "safety_check"} <= set(r.metrics.latency_ms)
    assert r.metrics.tokens_out >= 3 * 210  # thinking tokens counted as output


def test_plan_failure_retries_plan_then_fallback(tmp_path):
    stub = prime(LlmStub(bad={"plan_statements": 1}), "D02", tmp_path)
    r, _ = run(tmp_path, "D02", stub)
    assert stub.calls.count("plan_statements") == 2 and r.explanations[0].source == "llm"
    assert r.metrics.retries == 1

    stub = prime(LlmStub(bad={"plan_statements": 99}), "D02", tmp_path)
    r, _ = run(tmp_path, "D02", stub)
    assert stub.calls.count("plan_statements") == 3  # 1 + max 2 retries
    assert all(e.source == "template_fallback" for e in r.explanations)
    assert r.status == "partial"
    assert any(w.startswith("explanation came from template fallback") for w in r.warnings)
    assert r.recommendation.next_step == "follow_up_test_package"


def test_render_failure_retries_only_that_language(tmp_path):
    stub = prime(LlmStub(bad={"render_hi": 1}), "D02", tmp_path)
    r, _ = run(tmp_path, "D02", stub)
    assert stub.calls.count("plan_statements") == 1
    assert stub.calls.count("render_en") == 1 and stub.calls.count("render_hi") == 2
    assert all(e.source == "llm" for e in r.explanations)

    stub = prime(LlmStub(bad={"render_hi": 99}), "D02", tmp_path)
    r, _ = run(tmp_path, "D02", stub)
    assert stub.calls.count("render_hi") == 3 and stub.calls.count("render_en") == 1
    assert all(e.source == "template_fallback" for e in r.explanations)


def test_budget_exceeded_falls_back_with_flags_and_next_step(tmp_path):
    stub = prime(LlmStub(), "D02", tmp_path)
    # The extract call itself is allowed, but its billed usage uses up the guard.
    r, _ = run(tmp_path, "D02", stub, guard_inr=5.0, extract_in=1_000_000)
    assert stub.calls == []
    assert all(e.source == "template_fallback" for e in r.explanations)
    assert any("budget guard" in w for w in r.warnings) and r.status == "partial"
    assert r.tests and r.recommendation.next_step == "follow_up_test_package"


def test_budget_exhausted_at_extract_is_clean_rejection(tmp_path):
    g = BudgetGuard(tmp_path / "b.sqlite", guard_inr=1.0)
    g.record("seed", 100_000_000, 0)  # cap already reached
    calls = []

    async def extract_stub(doc, hint):
        calls.append(1)
        raise AssertionError("must not be called")
    r = asyncio.run(pipeline.run("data/reports/source/D02.pdf", caller=extract_stub,
                                 explain_caller=LlmStub(), guard=g))
    assert r.status == "rejected" and r.reason == "budget_exhausted" and calls == []


def test_critical_starts_with_urgent_template_both_languages(tmp_path):
    stub = prime(LlmStub(), "D03", tmp_path)
    r, _ = run(tmp_path, "D03", stub)
    assert all(e.source == "llm" for e in r.explanations)
    for e in r.explanations:
        assert e.urgent_message and e.urgent_message.startswith(
            "URGENT" if e.language == "en" else "तुरंत")


def test_real_upload_never_cached(tmp_path):
    cache = ResponseCache(tmp_path / "c.sqlite")
    stub = prime(LlmStub(), "D02", tmp_path)
    run(tmp_path, "D02", stub, real_upload=True, cache=cache)
    with sqlite3.connect(cache.path) as c:
        assert c.execute("SELECT COUNT(*) FROM responses").fetchone()[0] == 0
    run(tmp_path, "D02", stub, real_upload=False, cache=cache)
    n = len(stub.calls)
    run(tmp_path, "D02", stub, real_upload=False, cache=cache)
    assert len(stub.calls) == n  # synthetic: second run fully cached
