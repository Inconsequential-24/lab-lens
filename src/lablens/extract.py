"""extract (LLM): redacted report -> Extraction, with response cache and budget guard (PLAN.md 4, 8, 9)."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Awaitable, Callable

from pydantic import BaseModel

from lablens import cache as cache_mod, config, reference
from lablens.budget import BudgetGuard
from lablens.redact import RedactedDoc
from lablens.schemas import Extraction
from lablens.validate import map_test_id, missing_expected

log = logging.getLogger("lablens.extract")
PROMPT_PATH = Path(__file__).parent / "prompts" / "extract_v1.md"
EST_OUT = 2500  # generous output estimate for the budget reservation
EST_IMAGE_TOKENS = 1300


class Usage(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_thinking: int = 0
    tokens_cached: int = 0
    calls: int = 0
    cache_hits: int = 0
    cost_inr: float = 0.0

    def add(self, other: "Usage") -> None:
        for f in type(self).model_fields:
            setattr(self, f, getattr(self, f) + getattr(other, f))


class NoOutput(RuntimeError):
    """Model answered without a parsable extraction; carries the billed usage."""
    def __init__(self, usage: "Usage"):
        super().__init__("extract: model returned no output")
        self.usage = usage


LlmCaller = Callable[[RedactedDoc, str | None], Awaitable[tuple[Extraction, Usage]]]


class ProviderUnavailable(Exception):
    """Provider refused the call (429 after retries, or another non-5xx API error)."""


RATE_RETRIES = 2          # extra attempts after a 429
RATE_MAX_WAIT_S = 60.0    # cap on total backoff per call
RATE_BASE_DELAY_S = 2.0
_sleep = asyncio.sleep    # monkeypatched in tests


def _rate_limited(e: Exception) -> bool:
    return getattr(e, "code", None) == 429 or getattr(e, "status", None) == "RESOURCE_EXHAUSTED"


def _retry_after(e: Exception) -> float | None:
    """Retry hint from google.rpc.RetryInfo ("retryDelay": "17s") or a Retry-After header."""
    det = getattr(e, "details", None)
    if isinstance(det, dict):
        for d in det.get("error", det).get("details") or []:
            m = re.fullmatch(r"(\d+(?:\.\d+)?)s", str(d.get("retryDelay", ""))) \
                if isinstance(d, dict) else None
            if m:
                return float(m.group(1))
    try:
        return float(e.response.headers.get("retry-after"))  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError):
        return None


async def with_rate_retry(attempt: Callable[[], Awaitable]):
    """Run attempt(); retry a 429 up to RATE_RETRIES times honouring retry hints (total wait
    capped at RATE_MAX_WAIT_S). Other non-5xx API errors, or a 429 after retries, become
    ProviderUnavailable; ServerError propagates to the node-level retry. Each attempt
    settles/releases its own budget reservation."""
    from google.genai import errors
    waited = 0.0
    for n in range(RATE_RETRIES + 1):
        try:
            return await attempt()
        except errors.ServerError:
            raise
        except errors.APIError as e:
            delay = min(_retry_after(e) or RATE_BASE_DELAY_S * 2 ** n, RATE_MAX_WAIT_S - waited)
            if not _rate_limited(e) or n == RATE_RETRIES or delay <= 0:
                raise ProviderUnavailable(f"{getattr(e, 'code', '?')} {getattr(e, 'status', '')}") from e
            log.warning("provider rate-limited (429); retry %d in %.1fs", n + 1, delay)
            await _sleep(delay)
            waited += delay


@lru_cache(maxsize=1)
def instruction() -> str:
    catalog = "Catalog of test ids: " + " ".join(reference.load_tests())
    # Fixed parts only: report content goes in the user message, last (section 9.2).
    return cache_mod.build_prompt({"system_rules": PROMPT_PATH.read_text(encoding="utf-8"),
                                   "schema": catalog}, "").strip()


def version() -> str:
    return cache_mod.pipeline_version({
        "node": "extract", "prompt": hashlib.sha256(instruction().encode()).hexdigest(),
        "model": config.MODEL_NAME, "reference": reference.load_yaml("panels.yaml")["version"]})


def report_tag() -> str:
    return f"report-{secrets.token_hex(8)}"


def _message_parts(doc: RedactedDoc, hint: str | None):
    from google.genai import types
    parts = []
    # Random per-call delimiter: report text cannot close it early with a literal "</report>".
    tag = report_tag()
    if hint:
        parts.append(types.Part(text=hint))
    if doc.kind == "text":
        parts.append(types.Part(text=f"<{tag}>\n{doc.text}\n</{tag}>"))
    else:
        parts.append(types.Part(text=f"<{tag}> (page images follow) </{tag}>"))
        parts += [types.Part.from_bytes(data=base64.b64decode(b), mime_type=doc.mime)
                  for b in doc.images_b64]
    return parts


def make_agent():
    from google.adk import Agent
    from google.genai import types
    return Agent(
        name="extract_llm", model=config.MODEL_NAME, instruction=instruction(),
        output_schema=Extraction, output_key="extraction",
        generate_content_config=types.GenerateContentConfig(
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)),
    )


async def gemini_call(doc: RedactedDoc, hint: str | None) -> tuple[Extraction, Usage]:
    """One live call through ADK's Runner; usage summed from event.usage_metadata."""
    from dotenv import load_dotenv
    from google.adk import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    load_dotenv()  # GOOGLE_API_KEY; never logged
    runner = Runner(node=make_agent(), app_name="lablens_extract",
                    session_service=InMemorySessionService(), auto_create_session=True)
    msg = types.Content(role="user", parts=_message_parts(doc, hint))
    usage, out = Usage(calls=1), None
    async for ev in runner.run_async(user_id="extract", session_id="extract", new_message=msg):
        um = getattr(ev, "usage_metadata", None)
        if um:
            usage.tokens_in += um.prompt_token_count or 0
            usage.tokens_out += um.candidates_token_count or 0
            usage.tokens_thinking += um.thoughts_token_count or 0
            usage.tokens_cached += um.cached_content_token_count or 0
        # An Agent run as root puts its typed output in the output_key state delta.
        delta = ev.actions.state_delta if ev.actions else None
        if delta and delta.get("extraction") is not None:
            out = delta["extraction"]
        elif ev.output is not None:
            out = ev.output
    if out is None:
        raise NoOutput(usage)
    return (out if isinstance(out, Extraction) else Extraction.model_validate(out)), usage


def _estimate_in(doc: RedactedDoc) -> int:
    return (len(instruction()) + len(doc.text)) // 3 + EST_IMAGE_TOKENS * len(doc.images_b64)


async def _one_call(doc: RedactedDoc, hint: str | None, node: str, file_sha: str, real_upload: bool,
                    cache: cache_mod.ResponseCache | None, guard: BudgetGuard,
                    caller: LlmCaller) -> tuple[Extraction, Usage]:
    ver = version()
    if cache is not None:
        hit = cache.get(file_sha, node, ver, real_upload=real_upload)
        if hit is not None:
            return Extraction.model_validate(hit), Usage(cache_hits=1)

    async def attempt():
        rid = guard.check(_estimate_in(doc), EST_OUT)  # raises BudgetExceeded
        settled = False
        try:
            ext, usage = await caller(doc, hint)
            usage.cost_inr = guard.record(node, usage.tokens_in, usage.tokens_out,
                                          usage.tokens_thinking, reservation=rid)
            settled = True
            return ext, usage
        except NoOutput as e:
            guard.record(node, e.usage.tokens_in, e.usage.tokens_out, e.usage.tokens_thinking,
                         status="no_output", reservation=rid)
            settled = True
            raise
        finally:
            if not settled:
                guard.release(rid)  # failed/cancelled request (incl. CancelledError/429)

    ext, usage = await with_rate_retry(attempt)
    log.info("%s tokens in=%d out=%d thinking=%d cached=%d cost_inr=%.4f", node, usage.tokens_in,
             usage.tokens_out, usage.tokens_thinking, usage.tokens_cached, usage.cost_inr)
    if cache is not None:
        cache.put(file_sha, node, ver, ext.model_dump(mode="json"), real_upload=real_upload)
    return ext, usage


async def extract_report(doc: RedactedDoc, file_sha: str, *, real_upload: bool,
                         cache: cache_mod.ResponseCache | None = None, guard: BudgetGuard | None = None,
                         caller: LlmCaller | None = None) -> tuple[Extraction, Usage]:
    """Extract once; if expected panel tests are missing, one targeted retry, merging found rows."""
    guard = guard or BudgetGuard()
    caller = caller or gemini_call
    total = Usage()
    args = (file_sha, real_upload, cache, guard, caller)
    ext, u = await _one_call(doc, None, "extract", *args)
    total.add(u)
    missing = missing_expected(ext.tests)
    if missing:
        hint = ("A previous reading missed these expected tests. Check carefully whether each is "
                "printed in the report and extract every result row again: " + ", ".join(missing))
        retry, u = await _one_call(doc, hint, "extract_retry", *args)
        total.add(u)
        have = {map_test_id(r.raw_name, r.test_id_hint)[0] for r in ext.tests}
        new = [r for r in retry.tests if map_test_id(r.raw_name, r.test_id_hint)[0] not in have]
        ext = ext.model_copy(update={"tests": [*ext.tests, *new]})
    return ext, total
