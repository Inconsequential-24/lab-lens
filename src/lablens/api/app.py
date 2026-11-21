"""FastAPI service, milestone 11 (PLAN.md sections 6, 9.1, 10, 11; contract: openapi.yaml).

Logs carry only request ID, method, path, status, timings and error codes; never report
content, file names or tokens. Real uploads stay in process memory (never disk/cache/logs).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
import tempfile
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from lablens import config, history, input_guard, pipeline
from lablens.api import demo
from lablens.api.auth import GoogleIdTokenVerifier, TokenVerifier, bearer_token
from lablens.api.limits import TokenBucket
from lablens.budget import BudgetGuard
from lablens.cache import ResponseCache, file_sha256

log = logging.getLogger("lablens.api")
MAX_BODY = input_guard.MAX_BYTES + 64 * 1024  # file plus multipart overhead and small fields
LANGUAGES = {"en", "hi", "both"}
REPORT_TYPES = {"synthetic", "real"}
# input_guard / pipeline reasons -> openapi.yaml Error.reason
REASON_MAP = {"corrupt_pdf": "corrupted_file", "corrupt_image": "corrupted_file",
              "empty_file": "corrupted_file", "image_too_large": "file_too_large",
              "page_too_large": "file_too_large"}
MESSAGES = {
    "unsupported_file_type": "Only PDF, PNG or JPG files are supported.",
    "file_too_large": "Files up to 5 MB (and normal page/image sizes) are supported in the demo.",
    "too_many_pages": "Reports longer than 10 pages are not supported in the demo.",
    "zero_pages": "This PDF has no pages.",
    "encrypted_pdf": "Password-protected PDFs are not supported. Please upload an unlocked copy.",
    "corrupted_file": "This file could not be read. It may be damaged.",
    "not_a_lab_report": "This does not look like a lab report.",
    "invalid_language": "language must be en, hi or both.",
    "invalid_report_type": "report_type must be synthetic or real.",
    "auth_required": "Sign in with Google to use this feature.",
    "real_upload_not_enabled": "Real reports need sign-in and are not enabled on this server.",
    "not_found": "Report not found or expired.",
    "rate_limited": "Too many requests from this address. Try again later.",
    "daily_cap_reached": "The demo's daily budget is used up. Sample reports already processed "
                         "today are still available.",
    "provider_unavailable": "The service is temporarily unavailable.",
    "not_implemented": "This endpoint is not available yet.",
    "consent_required": "Tick the consent box to save this report to your history.",
    "report_date_required": "Enter the report date before saving.",
    "report_date_invalid": "The report date must be a valid date (YYYY-MM-DD).",
    "report_date_in_future": "The report date cannot be in the future.",
    "report_date_too_old": "The report date cannot be before 1990.",
    "invalid_overlap_choice": "overlap_choice values must be keep_new, keep_existing or keep_both.",
    "invalid_test_id": "test_id is required.",
    "already_saved": "This report is already saved.",
    "overlap": "Some tests are already saved for this date. Choose which values to keep.",
}
CAP_WARNING = "daily_cap_reached: served a cached result; new reports are paused until tomorrow"


class ApiError(Exception):
    def __init__(self, status: int, reason: str, headers: dict | None = None, message: str | None = None,
                 extra: dict | None = None):
        self.status, self.reason, self.headers = status, reason, headers or {}
        self.message = message or MESSAGES.get(reason, reason)
        self.extra = extra or {}


class _MemoryParser(MultiPartParser):
    spool_max_size = MAX_BODY  # keep the whole upload in memory, never a temp file


class ResultStore:
    """report_id -> result, in process memory with per-entry TTL (24 h synthetic, 60 min real)."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock, self._d, self._lock = clock, {}, threading.Lock()
        self._sha: dict[str, str] = {}  # report_id -> full file SHA-256 (duplicate check on save)

    def put(self, report_id: str, result: dict, ttl_s: float, owner: str | None, real: bool,
            sha: str | None = None) -> None:
        with self._lock:
            self._purge()
            self._d[report_id] = (self.clock() + ttl_s, result, owner, real)
            if sha:
                self._sha[report_id] = sha

    def sha(self, report_id: str) -> str | None:
        with self._lock:
            self._purge()
            return self._sha.get(report_id)

    def get(self, report_id: str) -> tuple[dict, str | None, bool] | None:
        with self._lock:
            self._purge()
            hit = self._d.get(report_id)
        return None if hit is None else hit[1:]

    def _purge(self) -> None:
        now = self.clock()
        for k in [k for k, v in self._d.items() if v[0] <= now]:
            del self._d[k]
            self._sha.pop(k, None)


@contextlib.contextmanager
def memory_path(data: bytes):
    """A filesystem path whose reads come from memory (a FIFO fed by a thread), so the
    path-based pipeline can process a real upload without its bytes touching disk.
    Every open() of the path gets one full copy until the context exits."""
    d = tempfile.mkdtemp(prefix="lablens-")
    fifo = os.path.join(d, "upload")
    os.mkfifo(fifo, 0o600)
    stop = threading.Event()

    def feed():
        while True:
            try:
                fd = os.open(fifo, os.O_WRONLY)
            except OSError:
                return
            try:
                if stop.is_set():
                    return
                with contextlib.suppress(BrokenPipeError):
                    view = memoryview(data)
                    while view:
                        view = view[os.write(fd, view):]
            finally:
                os.close(fd)

    t = threading.Thread(target=feed, daemon=True)
    t.start()
    try:
        yield fifo
    finally:
        stop.set()
        with contextlib.suppress(OSError):  # unblock a writer waiting for a reader
            os.close(os.open(fifo, os.O_RDONLY | os.O_NONBLOCK))
        t.join(timeout=2)
        os.unlink(fifo)
        os.rmdir(d)


def _utc_midnight() -> float:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _filter_language(result: dict, language: str) -> dict:
    if language == "both":
        return result
    return {**result, "explanations": [e for e in result["explanations"] if e["language"] == language]}


def create_app(*, cache: ResponseCache | None = None, guard: BudgetGuard | None = None,
               caller=None, explain_caller=None, verifier: TokenVerifier | None = None,
               frontend_dist: Path | None = None, paid_tier: bool | None = None,
               daily_cap_inr: float | None = None, reports_per_hour: int | None = None,
               reads_per_minute: int | None = None,
               history_store: history.HistoryStore | None = None) -> FastAPI:
    app = FastAPI(title="Lab Report Explainer API", version="0.1.0", docs_url=None, redoc_url=None)
    st = app.state
    st.cache, st.guard = cache, guard
    st.caller, st.explain_caller = caller, explain_caller
    st.verifier = verifier or GoogleIdTokenVerifier()
    st.paid_tier = config.PAID_TIER_KEY if paid_tier is None else paid_tier
    st.daily_cap = config.DAILY_CAP_INR if daily_cap_inr is None else daily_cap_inr
    st.upload_limit = TokenBucket(reports_per_hour or config.RATE_LIMIT_REPORTS_PER_HOUR, 3600)
    st.read_limit = TokenBucket(reads_per_minute or config.RATE_LIMIT_READS_PER_MINUTE, 60)
    st.results = ResultStore()
    st.history = history_store

    def _cache() -> ResponseCache:
        if st.cache is None:
            st.cache = ResponseCache()
        return st.cache

    def _history() -> history.HistoryStore:
        if st.history is None:
            st.history = history.HistoryStore()
        return st.history

    def _guard() -> BudgetGuard:
        if st.guard is None:
            st.guard = BudgetGuard()
        return st.guard

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = "req_" + secrets.token_hex(8)
        request.state.rid = rid
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("rid=%s %s %s unhandled", rid, request.method, request.url.path)
            response = JSONResponse({"reason": "provider_unavailable",
                                     "message": MESSAGES["provider_unavailable"]}, 503)
        response.headers["X-Request-ID"] = rid
        log.info("rid=%s %s %s status=%s ms=%.0f", rid, request.method, request.url.path,
                 response.status_code, (time.perf_counter() - t0) * 1000)
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, e: ApiError):
        log.info("rid=%s error=%s", getattr(request.state, "rid", "-"), e.reason)
        return JSONResponse({"reason": e.reason, "message": e.message, **e.extra}, e.status,
                            headers=e.headers)

    def limit(request: Request, bucket: TokenBucket) -> dict[str, str]:
        d = bucket.take(_client_ip(request))
        if not d.allowed:
            raise ApiError(429, "rate_limited", d.headers())
        return d.headers()

    def session(request: Request) -> str | None:
        token = bearer_token(request.headers.get("authorization"))
        return st.verifier(token) if token else None

    async def parse_upload(request: Request) -> tuple[bytes, str, str]:
        if "multipart/form-data" not in request.headers.get("content-type", ""):
            raise ApiError(400, "unsupported_file_type", message="Send multipart/form-data with a `file` field.")
        try:
            if int(request.headers.get("content-length") or 0) > MAX_BODY:
                raise ApiError(400, "file_too_large")
        except ValueError:
            raise ApiError(400, "corrupted_file", message="Invalid Content-Length.") from None
        body = bytearray()
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_BODY:
                raise ApiError(400, "file_too_large")

        async def one() -> AsyncIterator[bytes]:
            yield bytes(body)

        try:
            form = await _MemoryParser(request.headers, one(), max_files=1, max_fields=4,
                                       max_part_size=1024).parse()
        except MultiPartException:
            raise ApiError(400, "corrupted_file", message="Malformed multipart upload.") from None
        f = form.get("file")
        if not isinstance(f, UploadFile):
            raise ApiError(400, "unsupported_file_type", message="Missing `file` field.")
        data = await f.read()
        await f.close()
        language = str(form.get("language") or "both")
        report_type = str(form.get("report_type") or "synthetic")
        if language not in LANGUAGES:
            raise ApiError(400, "invalid_language")
        if report_type not in REPORT_TYPES:
            raise ApiError(400, "invalid_report_type")
        if len(data) > input_guard.MAX_BYTES:
            raise ApiError(400, "file_too_large")
        return data, language, report_type

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.post("/v1/reports")
    async def create_report(request: Request):
        headers = limit(request, st.upload_limit)
        data, language, report_type = await parse_upload(request)
        real = report_type == "real"
        owner = None
        if real:
            owner = await asyncio.to_thread(session, request)
            if owner is None:
                raise ApiError(401, "auth_required", headers)
            if not st.paid_tier:
                raise ApiError(403, "real_upload_not_enabled", headers)

        guard = _guard()
        today = guard.spent_since(_utc_midnight())
        if today >= st.daily_cap:
            if not real:  # past the cap only already-processed synthetic results are served
                hit = st.results.get(file_sha256(data)[:16])
                if hit and not hit[2]:
                    res = {**hit[0], "warnings": [*hit[0]["warnings"], CAP_WARNING]}
                    return JSONResponse(_filter_language(res, language), headers=headers)
            raise ApiError(503, "daily_cap_reached", headers)
        # The run may spend at most what is left of today's cap (and never past the global guard).
        run_guard = BudgetGuard(guard.path, min(guard.guard_inr,
                                                guard.spent_inr() + st.daily_cap - today))

        async def go(path: str):
            return await asyncio.wait_for(pipeline.run(
                path, real_upload=real, cache=_cache(), guard=run_guard, caller=st.caller,
                explain_caller=st.explain_caller), timeout=config.REQUEST_TIMEOUT_S)

        try:
            with memory_path(data) as path:
                out = await go(path)
        except asyncio.TimeoutError:
            raise ApiError(503, "provider_unavailable", headers) from None

        if isinstance(out, pipeline.Rejected):
            if out.reason == "budget_exhausted":
                raise ApiError(503, "daily_cap_reached", headers)
            reason = REASON_MAP.get(out.reason, out.reason)
            if reason not in MESSAGES:
                reason = "corrupted_file"
            raise ApiError(400, reason, headers)
        result = out.model_dump(mode="json")
        if not result["tests"]:
            raise ApiError(422, "no_tests_extracted", headers,
                           "No test results could be read from this file.")
        ttl = config.REAL_RESULT_TTL_S if real else config.SYNTHETIC_RESULT_TTL_S
        st.results.put(result["report_id"], result, ttl, owner, real, sha=file_sha256(data))
        return JSONResponse(_filter_language(result, language), headers=headers)

    @app.get("/v1/reports/{report_id}")
    async def get_report(report_id: str, request: Request):
        headers = limit(request, st.read_limit)
        hit = st.results.get(report_id)
        if hit is None:
            raise ApiError(404, "not_found", headers)
        result, owner, real = hit
        if real and (owner is None or await asyncio.to_thread(session, request) != owner):
            raise ApiError(404, "not_found", headers)  # not owned: indistinguishable from missing
        return JSONResponse(result, headers=headers)

    async def not_implemented(request: Request):
        headers = limit(request, st.read_limit)
        raise ApiError(501, "not_implemented", headers)

    app.add_api_route("/v1/reports/{report_id}/chat", not_implemented, methods=["POST"])

    # ---- opt-in saved history (PLAN.md sections 4.3, 6, 10) ----
    async def signed_in(request: Request) -> tuple[str, dict]:
        headers = limit(request, st.read_limit)
        user = await asyncio.to_thread(session, request)
        if user is None:
            raise ApiError(401, "auth_required", headers)
        store = _history()
        await asyncio.to_thread(store.purge_inactive)
        await asyncio.to_thread(store.touch, user)  # counts as a sign-in for retention
        return user, headers

    def parse_save(body: Any, headers: dict) -> tuple[str, date, dict[str, str]]:
        if not isinstance(body, dict) or body.get("consent") is not True:
            raise ApiError(400, "consent_required", headers)
        nv = body.get("notice_version")
        if not isinstance(nv, str) or not nv.strip() or len(nv) > 64:
            raise ApiError(400, "consent_required", headers, "notice_version is required.")
        raw = body.get("report_date")
        if raw in (None, ""):
            raise ApiError(400, "report_date_required", headers)
        try:
            d = date.fromisoformat(raw) if isinstance(raw, str) and len(raw) == 10 else None
        except ValueError:
            d = None
        if d is None:
            raise ApiError(400, "report_date_invalid", headers)
        # Allow the user's local "today" in any time zone (UTC+14 at most).
        if d > (datetime.now(timezone.utc) + timedelta(hours=14)).date():
            raise ApiError(400, "report_date_in_future", headers)
        if d < date.fromisoformat(config.HISTORY_MIN_REPORT_DATE):
            raise ApiError(400, "report_date_too_old", headers)
        choice = body.get("overlap_choice") or {}
        if not isinstance(choice, dict) or any(
                not isinstance(k, str) or v not in history.CHOICES for k, v in choice.items()):
            raise ApiError(400, "invalid_overlap_choice", headers)
        return nv.strip(), d, choice

    @app.post("/v1/reports/{report_id}/save")
    async def save_report(report_id: str, request: Request):
        user, headers = await signed_in(request)
        try:
            body = await request.json()
        except Exception:
            body = None
        nv, d, choice = parse_save(body, headers)
        hit = st.results.get(report_id)
        sha = st.results.sha(report_id)
        # Only real uploads owned by this user, still in memory (section 10); others look missing.
        if hit is None or not hit[2] or hit[1] != user or not sha:
            raise ApiError(404, "not_found", headers)
        result = hit[0]
        source = "extracted_confirmed" if result.get("report_date") == d.isoformat() else "user_entered"
        try:
            saved = await asyncio.to_thread(
                _history().save, user, tests=result["tests"], report_date=d, date_source=source,
                file_sha=sha, notice_version=nv, overlap_choice=choice)
        except history.AlreadySaved as e:
            raise ApiError(409, "already_saved", headers,
                           f"This report is already saved (saved on {e.saved_on.isoformat()}).",
                           {"saved_on": e.saved_on.isoformat()}) from None
        except history.Overlap as e:
            raise ApiError(409, "overlap", headers, extra={"overlaps": e.overlaps}) from None
        return JSONResponse(saved.model_dump(mode="json"), 201, headers=headers)

    @app.get("/v1/history")
    async def list_history(request: Request):
        user, headers = await signed_in(request)
        reports = await asyncio.to_thread(_history().list, user)
        return JSONResponse({"reports": [r.model_dump(mode="json") for r in reports]}, headers=headers)

    @app.delete("/v1/history")
    async def delete_all_history(request: Request):
        user, headers = await signed_in(request)
        await asyncio.to_thread(_history().withdraw, user)
        return Response(status_code=204, headers=headers)

    @app.get("/v1/history/trends")
    async def history_trends(request: Request):
        user, headers = await signed_in(request)
        test_id = request.query_params.get("test_id", "").strip()
        if not test_id or len(test_id) > 64:
            raise ApiError(400, "invalid_test_id", headers)
        points = await asyncio.to_thread(_history().trends, user, test_id)
        return JSONResponse({"test_id": test_id, "points": points}, headers=headers)

    @app.delete("/v1/history/{report_id}")
    async def delete_history_item(report_id: str, request: Request):
        user, headers = await signed_in(request)
        if not await asyncio.to_thread(_history().delete_one, user, report_id):
            raise ApiError(404, "not_found", headers)
        return Response(status_code=204, headers=headers)

    @app.get("/v1/demo/reports")
    async def demo_list(request: Request):
        headers = limit(request, st.read_limit)
        return JSONResponse({"reports": list(demo.demo_reports())}, headers=headers)

    @app.get("/v1/demo/reports/{name}")
    async def demo_file(name: str, request: Request):
        headers = limit(request, st.read_limit)
        p = demo.demo_pdf(name.removesuffix(".pdf")) if name.endswith(".pdf") else None
        if p is None:
            raise ApiError(404, "not_found", headers)
        return FileResponse(p, media_type="application/pdf", headers=headers, filename=p.name)

    dist = Path(frontend_dist or config.FRONTEND_DIST)
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
