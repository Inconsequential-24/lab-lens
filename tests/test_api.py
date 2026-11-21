"""API tests (milestone 11) with FastAPI TestClient; LLM callers are stubs, no live calls."""
import json
import logging
import sqlite3
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from lablens.api.app import CAP_WARNING, create_app
from lablens.api.limits import TokenBucket
from lablens.budget import BudgetGuard
from lablens.cache import ResponseCache
from lablens.extract import NoOutput, Usage
from lablens.schemas import Extraction, ExtractedRow

ROOT = Path(__file__).resolve().parents[1]
D02 = ROOT / "data/reports/source/D02.pdf"
GT = json.loads((ROOT / "data/ground_truth/D02.json").read_text())


async def stub_caller(doc, hint):
    rows = [ExtractedRow(raw_name=t["printed_name"], value_raw=t["value"]["raw"], unit_raw=t["unit_raw"],
                         ref_raw=t["ref"]["raw"], ref_low=t["ref"]["low"], ref_high=t["ref"]["high"],
                         printed_flag=t["printed_flag"]) for t in GT["tests"]]
    return Extraction(tests=rows, report_date="2026-09-17"), Usage(calls=1, tokens_in=1000, tokens_out=500)


async def no_live_explain(node, instr, msg, schema):
    raise NoOutput(Usage())


class Verifier:
    def __call__(self, token):
        return {"good": "sub-1", "other": "sub-2"}.get(token)


@pytest.fixture
def make(tmp_path):
    def _make(**kw):
        kw.setdefault("paid_tier", False)
        app = create_app(cache=ResponseCache(tmp_path / "responses.sqlite"),
                         guard=BudgetGuard(tmp_path / "budget.sqlite"), caller=stub_caller,
                         explain_caller=no_live_explain, verifier=Verifier(),
                         frontend_dist=kw.pop("frontend_dist", tmp_path / "nodist"), **kw)
        return TestClient(app)
    return _make



def post(c, data, headers=None, **form):
    return c.post("/v1/reports", files={"file": ("r.pdf", data, "application/pdf")}, data=form,
                  headers=headers)


def cache_rows(tmp_path):
    with sqlite3.connect(tmp_path / "responses.sqlite") as c:
        return c.execute("SELECT COUNT(*) FROM responses").fetchone()[0]


def test_healthz(make):
    r = make().get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert r.headers["X-Request-ID"].startswith("req_")


def test_synthetic_happy_path_and_get(make, tmp_path, caplog):
    c = make()
    caplog.set_level(logging.DEBUG)
    r = post(c, D02.read_bytes(), language="en")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tests"] and {e["language"] for e in body["explanations"]} == {"en"}
    assert r.headers["X-RateLimit-Limit"] == "5" and r.headers["X-RateLimit-Remaining"] == "4"
    assert cache_rows(tmp_path) > 0  # synthetic results use the response cache
    g = c.get(f"/v1/reports/{body['report_id']}")
    assert g.status_code == 200 and g.json()["report_id"] == body["report_id"]
    assert c.get("/v1/reports/nope").json()["reason"] == "not_found"
    logs = caplog.text
    for t in GT["tests"]:  # no report content in logs
        assert t["printed_name"] + " " + t["value"]["raw"] not in logs
    assert "r.pdf" not in logs


@pytest.mark.parametrize("data,reason", [(b"hello world", "unsupported_file_type"),
                                         (b"%PDF-1.4 garbage", "corrupted_file")])
def test_bad_file_400(make, data, reason):
    r = post(make(), data)
    assert r.status_code == 400 and r.json()["reason"] == reason


def test_too_large_400(make):
    r = post(make(), b"%PDF" + b"0" * (5 * 1024 * 1024))
    assert r.status_code == 400 and r.json()["reason"] == "file_too_large"


def test_invalid_fields(make):
    assert post(make(), b"x", language="fr").json()["reason"] == "invalid_language"
    assert post(make(), b"x", report_type="mine").json()["reason"] == "invalid_report_type"
    r = make().post("/v1/reports", data={"language": "en"})
    assert r.status_code == 400


def test_rate_limit_429(make):
    c = make(reports_per_hour=2)
    assert post(c, b"x").status_code == 400
    assert post(c, b"x").status_code == 400
    r = post(c, b"x")
    assert r.status_code == 429 and r.json()["reason"] == "rate_limited"
    assert int(r.headers["Retry-After"]) > 0 and r.headers["X-RateLimit-Remaining"] == "0"
    assert "X-RateLimit-Limit" in r.headers and "X-RateLimit-Reset" in r.headers


def test_token_bucket_refills():
    now = [0.0]
    b = TokenBucket(2, 60, clock=lambda: now[0])
    assert b.take("ip").allowed and b.take("ip").allowed and not b.take("ip").allowed
    assert b.take("other").allowed
    now[0] = 30
    assert b.take("ip").allowed


def test_daily_cap_503_but_cached_sample_served(make, tmp_path):
    c = make(daily_cap_inr=1.0)
    first = post(c, D02.read_bytes())
    assert first.status_code == 200
    BudgetGuard(tmp_path / "budget.sqlite").record("test", 10_000_000, 0)  # well past ₹1 today
    again = post(c, D02.read_bytes())
    assert again.status_code == 200 and CAP_WARNING in again.json()["warnings"]
    other = post(c, (ROOT / "data/reports/source/D04.pdf").read_bytes())
    assert other.status_code == 503 and other.json()["reason"] == "daily_cap_reached"


def test_real_upload_requires_session(make):
    c = make(paid_tier=True)
    assert post(c, D02.read_bytes(), report_type="real").json()["reason"] == "auth_required"
    r = post(c, D02.read_bytes(), report_type="real", headers={"Authorization": "Bearer bad"})
    assert r.status_code == 401
    r = post(make(), D02.read_bytes(), report_type="real", headers={"Authorization": "Bearer good"})
    assert r.status_code == 403 and r.json()["reason"] == "real_upload_not_enabled"


def test_real_upload_never_cached_and_owner_only(make, tmp_path):
    c = make(paid_tier=True)
    r = post(c, D02.read_bytes(), report_type="real", headers={"Authorization": "Bearer good"})
    assert r.status_code == 200, r.text
    assert cache_rows(tmp_path) == 0
    assert not [p for p in tmp_path.rglob("*") if p.suffix in (".pdf", ".png", ".jpg")]
    rid = r.json()["report_id"]
    assert c.get(f"/v1/reports/{rid}").status_code == 404
    assert c.get(f"/v1/reports/{rid}", headers={"Authorization": "Bearer other"}).status_code == 404
    assert c.get(f"/v1/reports/{rid}", headers={"Authorization": "Bearer good"}).status_code == 200


def test_chat_endpoint_501(make):
    r = make().post("/v1/reports/x/chat")
    assert r.status_code == 501 and r.json()["reason"] == "not_implemented"


def test_demo_list_and_pdfs(make):
    c = make()
    reports = c.get("/v1/demo/reports").json()["reports"]
    specs = {x["id"]: x for x in yaml.safe_load((ROOT / "data/case_specs.yaml").read_text())["cases"]}
    assert [d["id"] for d in reports] == [f"D{i:02d}" for i in range(1, 16)]
    assert all(specs[d["id"]]["split"] == "source" for d in reports)
    cats = {d["id"]: d["category"] for d in reports}
    assert cats["D01"] == "normal" and cats["D03"] == "critical" and cats["D02"] == "abnormal"
    assert all(d["test_count"] > 0 and d["panel"] for d in reports)
    pdf = c.get(reports[0]["pdf_url"])
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    for bad in ["E01.pdf", "D16.pdf", "..%2Feval%2FE01.pdf", "D01", "%2E%2E%2Fheldout.pdf"]:
        assert c.get(f"/v1/demo/reports/{bad}").status_code == 404, bad


def test_static_frontend_when_dist_exists(make, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<h1>lab lens</h1>")
    c = make(frontend_dist=dist)
    assert "lab lens" in c.get("/").text
    assert c.get("/healthz").json() == {"status": "ok"}
    assert make().get("/").status_code == 404


def test_routes_match_contract(make):
    spec = yaml.safe_load((ROOT / "openapi.yaml").read_text())
    routes = {(r.path, m.lower()) for r in make().app.routes for m in getattr(r, "methods", ())}
    for path, ops in spec["paths"].items():
        path = path.replace("{demo_id}.pdf", "{name}")
        for method in ops:
            assert (path, method) in routes, (method, path)
