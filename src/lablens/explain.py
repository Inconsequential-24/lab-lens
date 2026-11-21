"""plan_statements and render_en/render_hi (LLM), with response cache and budget guard
(PLAN.md sections 4, 5, 8, 9). Code decides; these calls only write language."""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel, Field

from lablens import cache as cache_mod, config, reference
from lablens.budget import BudgetGuard
from lablens.extract import NoOutput, Usage, with_rate_retry
from lablens.glossary import glossary_lookup
from lablens.safety import SafetyFailure
from lablens.schemas import (Citation, Explanation, Flag, FlaggedTest, Recommendation,
                             Statement)
from lablens.templates import DISCLAIMER, LANGS, display_name, urgent_template

log = logging.getLogger("lablens.explain")
PROMPTS = Path(__file__).parent / "prompts"
PLAN_PROMPT, RENDER_PROMPT = PROMPTS / "plan_v1.md", PROMPTS / "render_v1.md"
EST_OUT = {"plan_statements": 1500, "render": 1500}  # generous reservation estimates
MAX_RETRIES = 2  # PLAN section 4: plan-level and render-level, each max 2 retries


class PlanClaim(BaseModel):
    claim_id: str
    content: str
    cites: list[Citation]


class Plan(BaseModel):
    """plan_statements output_schema: language-neutral claims with citations."""
    claims: list[PlanClaim]


class RenderedStatement(BaseModel):
    claim_id: str
    text: str


class Rendered(BaseModel):
    """render_* output_schema. Citations, urgent text and disclaimer are added by code."""
    summary: str
    statements: list[RenderedStatement]


# (node, instruction, message, output schema) -> (validated output, usage)
ExplainCaller = Callable[[str, str, str, type[BaseModel]], Awaitable[tuple[BaseModel, Usage]]]


def _safety_prefix() -> str:
    r = reference.load_yaml("safety_rules.yaml")
    lines = ["Banned phrases (never use, any form):"]
    for group, langs in r["banned"].items():
        for lang, words in langs.items():
            lines.append(f"- {group} ({lang}): " + "; ".join(words))
    d = r["direction"]
    lines.append("Direction words: low = " + "; ".join(d["low"]["en"] + d["low"]["hi"]) +
                 ". high = " + "; ".join(d["high"]["en"] + d["high"]["hi"]) +
                 ". Reassurance words (never in a statement about a low/high test): " +
                 "; ".join(d["normal"]["en"] + d["normal"]["hi"]) + ".")
    return "\n".join(lines)


@lru_cache(maxsize=2)
def instruction(kind: Literal["plan", "render"]) -> str:
    path = PLAN_PROMPT if kind == "plan" else RENDER_PROMPT
    # Fixed parts only; per-report data goes in the user message, last (section 9.2).
    return cache_mod.build_prompt({"system_rules": path.read_text(encoding="utf-8"),
                                   "safety_rules": _safety_prefix()}, "").strip()


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                     default=str).encode()).hexdigest()


def version(node: str, kind: str, payload, upstream: str | None) -> str:
    """Per-node chain: prompt, model, glossary version and the exact input (section 9.1)."""
    return cache_mod.pipeline_version({
        "node": node, "prompt": _sha(instruction(kind)), "model": config.MODEL_NAME,
        "glossary": reference.load_yaml("glossary.yaml")["version"],
        "safety": reference.load_yaml("safety_rules.yaml")["version"],
        "input": _sha(payload)}, upstream)


def plan_input(tests: list[FlaggedTest], rec: Recommendation) -> dict:
    """Only abnormal/unknown rows plus a normal count go to the LLM (section 8)."""
    recognised = [t for t in tests if t.test_id]
    gl = glossary_lookup([t.test_id for t in recognised])

    def row(t: FlaggedTest) -> dict:
        return {"test_id": t.test_id, "name": display_name(t, "en"),
                "name_hi": (gl.get(t.test_id) or {}).get("name_hi"),
                "value": t.value.raw, "unit": (t.unit_raw or "").strip() or None,
                "ref_range": t.ref.raw, "ref_low": t.ref.low, "ref_high": t.ref.high,
                "range_printed_on_report": t.ref.source == "report",
                "flag": t.flag.value, "severity": t.severity.value, "critical": t.is_critical,
                "lab_remark": t.remark}

    abnormal = [row(t) for t in recognised if t.flag in (Flag.LOW, Flag.HIGH)]
    unknown = [row(t) for t in recognised if t.flag is Flag.UNKNOWN
               and not reference.is_informational(t.test_id)]
    abn_ids = {r["test_id"] for r in abnormal}
    normal = sorted({t.test_id for t in recognised if t.flag is Flag.NORMAL} - abn_ids)
    glossary = {tid: {k: e[k]["en"] for k in ("measures", "low", "high") if k in e}
                for tid, e in gl.items() if tid in abn_ids}
    label = None
    if rec.next_step == "follow_up_test_package" and rec.package_id:
        label = reference.load_packages()[rec.package_id]["label"]
    return {"abnormal_tests": abnormal, "unknown_flag_tests": unknown,
            "normal_count": len(normal), "normal_test_ids": normal, "glossary": glossary,
            "recommendation": {"next_step": rec.next_step, "urgency": rec.urgency,
                               "package_label": label, "reason_test_ids": rec.reason_test_ids}}


def render_input(plan: Plan, lang: str, tests: list[FlaggedTest]) -> dict:
    names = {}
    for t in tests:
        if t.test_id:
            names[t.test_id] = display_name(t, lang)
    return {"language": lang, "test_names": names,
            "claims": [{"claim_id": c.claim_id, "content": c.content} for c in plan.claims]}


def message(payload: dict, feedback: str | None) -> str:
    # Random per-call delimiter: data cannot close it early with a literal closing tag.
    tag = f"data-{secrets.token_hex(8)}"
    head = f"{feedback}\n\n" if feedback else ""
    return f"{head}<{tag}>\n{json.dumps(payload, ensure_ascii=False)}\n</{tag}>"


def make_agent(node: str, instr: str, schema: type[BaseModel]):
    from google.adk import Agent
    from google.genai import types
    # Thinking at the minimum level: plan starts at minimum, render as close to off as the
    # model allows (section 8).
    return Agent(name=f"{node}_llm", model=config.MODEL_NAME, instruction=instr,
                 output_schema=schema, output_key="out",
                 generate_content_config=types.GenerateContentConfig(
                     temperature=0,
                     thinking_config=types.ThinkingConfig(
                         thinking_level=types.ThinkingLevel.MINIMAL)))


async def gemini_call(node: str, instr: str, msg: str,
                      schema: type[BaseModel]) -> tuple[BaseModel, Usage]:
    """One live call through a nested ADK Runner (same pattern as extract)."""
    from dotenv import load_dotenv
    from google.adk import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    load_dotenv()  # GOOGLE_API_KEY; never logged
    runner = Runner(node=make_agent(node, instr, schema), app_name=f"lablens_{node}",
                    session_service=InMemorySessionService(), auto_create_session=True)
    content = types.Content(role="user", parts=[types.Part(text=msg)])
    usage, out = Usage(calls=1), None
    async for ev in runner.run_async(user_id=node, session_id=node, new_message=content):
        um = getattr(ev, "usage_metadata", None)
        if um:
            usage.tokens_in += um.prompt_token_count or 0
            usage.tokens_out += um.candidates_token_count or 0
            usage.tokens_thinking += um.thoughts_token_count or 0
            usage.tokens_cached += um.cached_content_token_count or 0
        delta = ev.actions.state_delta if ev.actions else None
        if delta and delta.get("out") is not None:
            out = delta["out"]
        elif ev.output is not None:
            out = ev.output
    if out is None:
        raise NoOutput(usage)
    try:
        return (out if isinstance(out, schema) else schema.model_validate(out)), usage
    except ValueError as e:
        raise NoOutput(usage) from e


async def call(node: str, kind: str, payload: dict, feedback: str | None, schema: type[BaseModel],
               *, file_sha: str, real_upload: bool, upstream: str | None,
               cache: cache_mod.ResponseCache | None, guard: BudgetGuard,
               caller: ExplainCaller | None) -> tuple[BaseModel, Usage, str]:
    """Cache (synthetic only) -> budget reservation -> call -> settle. Raises BudgetExceeded
    NoOutput or ProviderUnavailable; the pipeline turns both into template_fallback."""
    caller = caller or gemini_call
    ver = version(node, kind, {"payload": payload, "feedback": feedback}, upstream)
    if cache is not None:
        hit = cache.get(file_sha, node, ver, real_upload=real_upload)
        if hit is not None:
            return schema.model_validate(hit), Usage(cache_hits=1), ver
    instr, msg = instruction(kind), message(payload, feedback)

    async def attempt():
        rid = guard.check((len(instr) + len(msg)) // 3, EST_OUT.get(node, EST_OUT["render"]))
        settled = False
        try:
            out, usage = await caller(node, instr, msg, schema)
            usage.cost_inr = guard.record(node, usage.tokens_in, usage.tokens_out,
                                          usage.tokens_thinking, reservation=rid)
            settled = True
            return out, usage
        except NoOutput as e:
            guard.record(node, e.usage.tokens_in, e.usage.tokens_out, e.usage.tokens_thinking,
                         status="no_output", reservation=rid)
            settled = True
            raise
        finally:
            if not settled:
                guard.release(rid)

    out, usage = await with_rate_retry(attempt)
    log.info("%s tokens in=%d out=%d thinking=%d cached=%d cost_inr=%.4f", node, usage.tokens_in,
             usage.tokens_out, usage.tokens_thinking, usage.tokens_cached, usage.cost_inr)
    if cache is not None:
        cache.put(file_sha, node, ver, out.model_dump(mode="json"), real_upload=real_upload)
    return out, usage, ver


def assemble(lang: str, plan: Plan, rendered: Rendered,
             tests: list[FlaggedTest]) -> tuple[Explanation, list[SafetyFailure]]:
    """Build the Explanation in code: citations come from the plan, the urgent text and the
    disclaimer are fixed templates. Claim coverage failures are render-level."""
    by_id = {c.claim_id: c for c in plan.claims}
    fails, stmts, seen = [], [], set()
    for s in rendered.statements:
        if s.claim_id not in by_id or s.claim_id in seen:
            fails.append(SafetyFailure("render", lang, s.claim_id, "claim_set_mismatch",
                                       "statement for an unknown or repeated claim"))
            continue
        seen.add(s.claim_id)
        cites = by_id[s.claim_id].cites
        if not cites:
            fails.append(SafetyFailure("plan", lang, s.claim_id, "missing_citation",
                                       "claim has no citations"))
            continue
        stmts.append(Statement(claim_id=s.claim_id, text=s.text, cites=cites))
    for cid in by_id.keys() - seen:
        fails.append(SafetyFailure("render", lang, cid, "claim_set_mismatch",
                                   "claim not rendered"))
    ex = Explanation(language=lang, source="llm", urgent_message=urgent_template(lang, tests),
                     summary=rendered.summary, statements=stmts, disclaimer=DISCLAIMER[lang])
    return ex, fails


def feedback(failures: list[SafetyFailure], stage: str) -> str:
    items = "; ".join(sorted({f"{f.claim_id or 'summary'}: {f.code} {f.detail}"
                              for f in failures}))
    return (f"A previous {stage} was rejected by the safety checker. Fix exactly these problems "
            f"and follow every rule: {items}")


__all__ = ["Plan", "Rendered", "LANGS", "MAX_RETRIES", "assemble", "call", "feedback",
           "plan_input", "render_input"]
