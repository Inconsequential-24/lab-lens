"""ADK Workflow (PLAN.md section 4): input_guard -> redact_pii -> extract -> validate ->
flag_engine -> decision -> plan_statements -> (render_en, render_hi) -> join -> safety_router
-> retry plan / retry one render / template_fallback -> finalize."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from google.adk import Context, Event, Runner, Workflow
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import RetryConfig, node
from google.genai import types
from pydantic import BaseModel

from lablens import cache as cache_mod, config, input_guard as guard_mod
from lablens import explain as ex_mod
from lablens.budget import BudgetExceeded, BudgetGuard
from lablens.decision import route_next_step
from lablens.extract import LlmCaller, NoOutput, Usage, extract_report, version as extract_version
from lablens.flag_engine import flag_tests
from lablens.ml.pattern_model import pattern_model
from lablens.redact import RedactedDoc, redact_pii
from lablens.safety import SafetyFailure, safety_check
from lablens.templates import template_fallback
from lablens.schemas import (Explanation, Extraction, FlaggedTest, Recommendation,
                             ReportResult, RunMetrics, ValidatedReport)
from google.adk.workflow import JoinNode
from lablens.validate import validate as validate_extraction

PIPELINE_ID = "explain_v1"
log = logging.getLogger("lablens.pipeline")
LLM_NODES = ("plan_statements", "render_en", "render_hi")
# Process-local wiring for things that cannot travel through session state.
RUNTIME: dict = {"cache": None, "guard": None, "caller": None, "explain_caller": None}


class Rejected(BaseModel):
    status: str = "rejected"
    reason: str


class Flagged(BaseModel):
    tests: list[FlaggedTest]


def _bytes(ctx: Context) -> bytes:
    return Path(ctx.state["path"]).read_bytes()


def input_guard(node_input: dict, ctx: Context):
    ctx.state["path"] = node_input["path"]
    ctx.state["real_upload"] = bool(node_input.get("real_upload", False))
    data = _bytes(ctx)
    ctx.state["file_sha"] = cache_mod.file_sha256(data)
    res = guard_mod.check(data)
    ctx.state["guard_kind"] = res.kind
    out = res.model_copy(update={"text": ""})  # raw text layer never enters session events
    return Event(output=out, route="OK" if res.ok else "REJECT")


def reject(node_input: guard_mod.GuardResult) -> str:
    return Rejected(reason=node_input.reason or "unknown").model_dump_json()


def budget_reject(node_input: str) -> str:
    return Rejected(reason="budget_exhausted").model_dump_json()


def _add_usage(ctx: Context, node_name: str, usage: Usage) -> None:
    # One key per node: render_en and render_hi run in parallel and must not race on one key.
    key = f"usage_{node_name}"
    prev = Usage.model_validate(ctx.state.get(key) or {})
    prev.add(usage)
    ctx.state[key] = prev.model_dump()


def _add_ms(ctx: Context, node_name: str, t0: float) -> None:
    key = f"ms_{node_name}"
    ctx.state[key] = (ctx.state.get(key) or 0.0) + (time.perf_counter() - t0) * 1000


def redact(node_input: guard_mod.GuardResult, ctx: Context) -> RedactedDoc:
    data = _bytes(ctx)
    text = guard_mod.check(data).text if node_input.kind == "pdf" else ""
    doc = redact_pii(data, node_input.kind or "image", text)
    ctx.state["redacted_text"] = doc.text
    return doc


# Cap: 2 node attempts on 5xx only x (call + 1 targeted retry) = at most 3 billed calls per report.
# BudgetExceeded is not retried: it routes to a clean "budget_exhausted" rejection (section 11).
@node(retry_config=RetryConfig(max_attempts=2, initial_delay=2.0, exceptions=["ServerError"]))
async def extract(node_input: RedactedDoc, ctx: Context):
    t0 = time.perf_counter()
    try:
        ext, usage = await extract_report(
            node_input, ctx.state["file_sha"], real_upload=ctx.state["real_upload"],
            cache=RUNTIME["cache"], guard=RUNTIME["guard"], caller=RUNTIME["caller"])
    except BudgetExceeded as e:
        log.warning("extract refused by budget guard: %s", e)
        return Event(output="budget_exhausted", route="BUDGET")
    _add_usage(ctx, "extract", usage)
    ctx.state["ms_extract"] = (time.perf_counter() - t0) * 1000
    return Event(output=ext, route="OK")


# ADK strips None values from node outputs (models and dicts), which breaks required-nullable
# fields such as ExtractedTest.remark, so these nodes hand data over via ctx.state as JSON.
def validate(node_input: Extraction, ctx: Context) -> str:
    v = validate_extraction(node_input, ctx.state.get("redacted_text", ""))
    ctx.state["validated"] = v.model_dump(mode="json")
    return "validated"


def flag_engine(node_input: str, ctx: Context) -> str:
    v = ValidatedReport.model_validate(ctx.state["validated"])
    ctx.state["flagged"] = Flagged(tests=flag_tests(v.tests)).model_dump(mode="json")
    return "flagged"


def _tests(ctx: Context) -> list[FlaggedTest]:
    return Flagged.model_validate(ctx.state["flagged"]).tests


def _rec(ctx: Context) -> Recommendation:
    return Recommendation.model_validate(ctx.state["rec"])


def decision(node_input: str, ctx: Context):
    """route_next_step runs before any explanation call, so flags and next step never wait."""
    tests = _tests(ctx)
    ctx.state["rec"] = route_next_step(tests).model_dump(mode="json")
    ctx.state["plan_attempts"] = 0
    if not any(t.test_id for t in tests):
        ctx.state["fallback_reason"] = "no recognised tests"
        return Event(output="decided", route="FALLBACK")
    return Event(output="decided", route="LLM")


def _stop_llm(ctx: Context, node_name: str, e: Exception) -> None:
    if isinstance(e, NoOutput):
        _add_usage(ctx, node_name, Usage(calls=1, **{k: getattr(e.usage, k) for k in
                                                     ("tokens_in", "tokens_out",
                                                      "tokens_thinking", "tokens_cached")}))
    reason = "budget guard refused the call" if isinstance(e, BudgetExceeded) else \
        "LLM unavailable or returned no usable output"
    log.warning("%s: %s; using template fallback", node_name, reason)
    ctx.state["fallback_reason"] = reason


def _llm_errors() -> tuple[type[Exception], ...]:
    from google.genai import errors
    return (BudgetExceeded, NoOutput, errors.APIError)


async def _call(ctx: Context, node_name: str, kind: str, payload: dict, fb: str | None,
                schema, upstream: str | None):
    out, usage, ver = await ex_mod.call(
        node_name, kind, payload, fb, schema, file_sha=ctx.state["file_sha"],
        real_upload=ctx.state["real_upload"], upstream=upstream, cache=RUNTIME["cache"],
        guard=RUNTIME["guard"], caller=RUNTIME["explain_caller"])
    _add_usage(ctx, node_name, usage)
    return out, ver


async def plan_statements(node_input, ctx: Context) -> str:
    t0 = time.perf_counter()
    ctx.state["plan_attempts"] = ctx.state["plan_attempts"] + 1
    try:
        plan, ver = await _call(ctx, "plan_statements", "plan",
                                ex_mod.plan_input(_tests(ctx), _rec(ctx)),
                                ctx.state.get("plan_feedback"), ex_mod.Plan, extract_version())
        ctx.state["plan"] = plan.model_dump(mode="json")
        ctx.state["plan_version"] = ver
    except _llm_errors() as e:
        _stop_llm(ctx, "plan_statements", e)
    _add_ms(ctx, "plan_statements", t0)
    return "planned"


async def _render(ctx: Context, lang: str, fb: str | None) -> None:
    t0 = time.perf_counter()
    node_name = f"render_{lang}"
    key = f"render_attempts_{lang}"
    ctx.state[key] = (ctx.state.get(key) or 0) + 1
    try:
        plan = ex_mod.Plan.model_validate(ctx.state["plan"])
        out, _ = await _call(ctx, node_name, "render",
                             ex_mod.render_input(plan, lang, _tests(ctx)), fb, ex_mod.Rendered,
                             ctx.state["plan_version"])
        ctx.state[node_name] = out.model_dump(mode="json")
    except _llm_errors() as e:
        _stop_llm(ctx, node_name, e)
    _add_ms(ctx, node_name, t0)


async def render_en(node_input, ctx: Context) -> str:
    if not ctx.state.get("fallback_reason"):
        ctx.state["render_attempts_en"] = 0
        await _render(ctx, "en", None)
    return "rendered_en"


async def render_hi(node_input, ctx: Context) -> str:
    if not ctx.state.get("fallback_reason"):
        ctx.state["render_attempts_hi"] = 0
        await _render(ctx, "hi", None)
    return "rendered_hi"


async def render_retry(node_input, ctx: Context) -> str:
    """Re-render only the failing language(s), with the checker's feedback."""
    langs = ctx.state["rerender"]
    await asyncio.gather(*(_render(ctx, l, ctx.state.get(f"render_feedback_{l}")) for l in langs))
    return "rerendered"


join_renders = JoinNode(name="join_renders")


def safety_router(node_input, ctx: Context):
    t0 = time.perf_counter()
    route = _route(ctx)
    _add_ms(ctx, "safety_check", t0)
    if route != "OK":
        ctx.state["retries"] = (ctx.state.get("retries") or 0) + (route in ("PLAN", "RENDER"))
    return Event(output=route.lower(), route=route)


def _route(ctx: Context) -> str:
    if ctx.state.get("fallback_reason"):
        return "FALLBACK"
    tests, plan = _tests(ctx), ex_mod.Plan.model_validate(ctx.state["plan"])
    exps, fails = [], []
    for lang in ex_mod.LANGS:
        e, f = ex_mod.assemble(lang, plan, ex_mod.Rendered.model_validate(
            ctx.state[f"render_{lang}"]), tests)
        exps.append(e)
        fails += f
    fails += safety_check(exps, tests, _rec(ctx))
    codes = ctx.state.get("safety_codes") or []
    ctx.state["safety_codes"] = codes + [sorted({f"{f.level}:{f.language}:{f.code}" for f in fails})]
    if not fails:
        ctx.state["explanations"] = [e.model_dump(mode="json") for e in exps]
        return "OK"
    plan_fails = [f for f in fails if f.level == "plan"]
    if plan_fails:
        if ctx.state["plan_attempts"] > ex_mod.MAX_RETRIES:
            ctx.state["fallback_reason"] = "safety_check failed after plan retries (" + \
                ", ".join(sorted({f.code for f in plan_fails})) + ")"
            return "FALLBACK"
        ctx.state["plan_feedback"] = ex_mod.feedback(plan_fails, "claim plan")
        return "PLAN"
    langs = sorted({f.language for f in fails if f.language in ex_mod.LANGS})
    if any((ctx.state.get(f"render_attempts_{l}") or 0) > ex_mod.MAX_RETRIES for l in langs):
        ctx.state["fallback_reason"] = "safety_check failed after render retries (" + \
            ", ".join(sorted({f.code for f in fails})) + ")"
        return "FALLBACK"
    for l in langs:
        ctx.state[f"render_feedback_{l}"] = ex_mod.feedback(
            [f for f in fails if f.language == l], f"{l} rendering")
    ctx.state["rerender"] = langs
    return "RENDER"


def fallback(node_input, ctx: Context) -> str:
    tests = _tests(ctx)
    exps = template_fallback(tests, _rec(ctx))
    warnings = ["explanation came from template fallback: " + ctx.state["fallback_reason"]]
    failures = safety_check(exps, tests, _rec(ctx))
    if failures:
        # Never show text that failed the checker; flags and the next step still go out.
        exps = []
        warnings.append("explanation withheld: failed safety check (" +
                        ", ".join(sorted({f.code for f in failures})) + ")")
    ctx.state["explanations"] = [e.model_dump(mode="json") for e in exps]
    ctx.state["explain_warnings"] = warnings
    return "fallback"


def finalize(node_input, ctx: Context) -> str:
    """Returns ReportResult as JSON text (see the None-stripping note above)."""
    tests = _tests(ctx)
    v = ValidatedReport.model_validate(ctx.state["validated"])
    rec = _rec(ctx)
    warnings = list(v.warnings) + list(ctx.state.get("explain_warnings") or [])
    if not v.tests and ctx.state.get("guard_kind") == "image":
        warnings.append("not_a_lab_report: no test rows found in the image")
    partial = bool(v.dropped_rows or v.unrecognised_tests or v.low_confidence_tests
                   or any(w.startswith("expected tests not found") for w in v.warnings)
                   or ctx.state.get("explain_warnings"))
    u = Usage()
    for n in ("extract", *LLM_NODES):
        u.add(Usage.model_validate(ctx.state.get(f"usage_{n}") or {}))
    latency = {n: ctx.state[f"ms_{n}"] for n in ("extract", *LLM_NODES, "safety_check")
               if ctx.state.get(f"ms_{n}") is not None}
    models = {n: config.MODEL_NAME for n in ("extract", *LLM_NODES)
              if ctx.state.get(f"usage_{n}")}
    return ReportResult(
        report_id=ctx.state["file_sha"][:16], status="partial" if partial else "complete",
        report_date=v.report_date, panels=v.panels, tests=tests,
        unrecognised_tests=v.unrecognised_tests, lab_remarks=v.lab_remarks,
        patterns=pattern_model(tests),
        explanations=[Explanation.model_validate(e) for e in ctx.state["explanations"]],
        recommendation=rec, low_confidence_tests=v.low_confidence_tests, warnings=warnings,
        metrics=RunMetrics(latency_ms=latency, tokens_in=u.tokens_in,
                           tokens_out=u.tokens_out + u.tokens_thinking,
                           tokens_cached=u.tokens_cached, cost_inr=u.cost_inr,
                           retries=ctx.state.get("retries") or 0,
                           model_versions=models)).model_dump_json()


def node_usage(result_state: dict) -> dict:
    return {n: result_state.get(f"usage_{n}") for n in ("extract", *LLM_NODES)}


workflow = Workflow(
    name="lablens",
    edges=[
        ("START", input_guard),
        (input_guard, {"OK": redact, "REJECT": reject}),
        (redact, extract),
        (extract, {"OK": validate, "BUDGET": budget_reject}),
        (validate, flag_engine, decision),
        (decision, {"LLM": plan_statements, "FALLBACK": fallback}),
        (plan_statements, (render_en, render_hi), join_renders, safety_router),
        (safety_router, {"OK": finalize, "PLAN": plan_statements, "RENDER": render_retry,
                         "FALLBACK": fallback}),
        (render_retry, safety_router),
        (fallback, finalize),
    ],
)


async def run(path: str | Path, *, real_upload: bool = False,
              cache: cache_mod.ResponseCache | None = None, guard: BudgetGuard | None = None,
              caller: LlmCaller | None = None,
              explain_caller: ex_mod.ExplainCaller | None = None,
              state_out: dict | None = None) -> ReportResult | Rejected:
    """state_out, if given, receives the final session state (per-node usage for evals)."""
    guard = guard or BudgetGuard()
    RUNTIME.update(cache=cache, guard=guard, caller=caller, explain_caller=explain_caller)
    runner = Runner(node=workflow, app_name="lablens", session_service=InMemorySessionService(),
                    auto_create_session=True)
    msg = types.Content(role="user", parts=[types.Part(text=json.dumps(
        {"path": str(path), "real_upload": real_upload}))])
    last = None
    async for ev in runner.run_async(user_id="u", session_id="s", new_message=msg):
        if ev.output is not None:
            last = ev.output
    if state_out is not None:
        sess = await runner.session_service.get_session(app_name="lablens", user_id="u",
                                                        session_id="s")
        state_out.update(sess.state if sess else {})
    if not isinstance(last, str):
        raise RuntimeError("pipeline produced no output")
    data = json.loads(last)
    return Rejected.model_validate(data) if data.get("status") == "rejected" \
        else ReportResult.model_validate(data)
