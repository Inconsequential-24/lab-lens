"""Opt-in saved history (milestone 12; PLAN.md 4.3, 6, 10, 11). Stub LLM callers, no live calls."""
import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from lablens.api.app import create_app
from lablens.budget import BudgetGuard
from lablens.cache import ResponseCache
from lablens.history import HistoryStore
from tests.test_api import D02, Verifier, no_live_explain, post, stub_caller

A = {"Authorization": "Bearer good"}
B = {"Authorization": "Bearer other"}
BODY = {"consent": True, "notice_version": "2026-11-v1", "report_date": "2026-09-17"}
ALLOWED_TEST_COLS = {"saved_report_id", "user_id", "test_id", "panel", "value_raw", "value_number",
                     "comparator", "unit_raw", "unit", "ref_raw", "ref_low", "ref_high",
                     "ref_source", "flag", "severity", "is_critical"}


@pytest.fixture
def c(tmp_path):
    app = create_app(cache=ResponseCache(tmp_path / "responses.sqlite"),
                     guard=BudgetGuard(tmp_path / "budget.sqlite"), caller=stub_caller,
                     explain_caller=no_live_explain, verifier=Verifier(), paid_tier=True,
                     frontend_dist=tmp_path / "nodist", history_store=HistoryStore(tmp_path / "h.sqlite"))
    return TestClient(app)


def upload(c, headers=A, extra=b""):
    r = post(c, D02.read_bytes() + extra, report_type="real", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["report_id"]


def save(c, rid, headers=A, **kw):
    return c.post(f"/v1/reports/{rid}/save", json={**BODY, **kw}, headers=headers)


def test_requires_sign_in(c):
    for m, p in [("post", "/v1/reports/x/save"), ("get", "/v1/history"), ("delete", "/v1/history"),
                 ("delete", "/v1/history/x"), ("get", "/v1/history/trends?test_id=LDL")]:
        r = getattr(c, m)(p)
        assert r.status_code == 401 and r.json()["reason"] == "auth_required", p


@pytest.mark.parametrize("body,reason", [
    ({**BODY, "consent": False}, "consent_required"),
    ({k: v for k, v in BODY.items() if k != "consent"}, "consent_required"),
    ({**BODY, "consent": "true"}, "consent_required"),
    ({k: v for k, v in BODY.items() if k != "report_date"}, "report_date_required"),
    ({**BODY, "report_date": "17/09/2026"}, "report_date_invalid"),
    ({**BODY, "report_date": "2026-02-30"}, "report_date_invalid"),
    ({**BODY, "report_date": (date.today() + timedelta(days=3)).isoformat()}, "report_date_in_future"),
    ({**BODY, "report_date": "1989-12-31"}, "report_date_too_old"),
    ({**BODY, "overlap_choice": {"LDL": "both"}}, "invalid_overlap_choice"),
])
def test_save_400(c, body, reason):
    rid = upload(c)
    r = c.post(f"/v1/reports/{rid}/save", json=body, headers=A)
    assert r.status_code == 400 and r.json()["reason"] == reason
    assert c.get("/v1/history", headers=A).json()["reports"] == []


def test_save_only_own_real_report_in_memory(c):
    assert save(c, "missing").status_code == 404
    rid = upload(c)
    assert save(c, rid, headers=B).status_code == 404  # other user's upload
    syn = post(c, D02.read_bytes() + b"\n%syn\n").json()["report_id"]
    assert save(c, syn).status_code == 404  # synthetic results are not saved (section 10)


def test_save_duplicate_and_date_source(c):
    rid = upload(c)
    r = save(c, rid)
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["user_id"] == "sub-1" and s["date_source"] == "extracted_confirmed"
    assert len(s["file_sha256"]) == 64 and s["consent_notice_version"] == "2026-11-v1"
    r = save(c, rid)
    assert r.status_code == 409 and r.json()["reason"] == "already_saved"
    assert r.json()["saved_on"] == "2026-09-17"
    assert len(c.get("/v1/history", headers=A).json()["reports"]) == 1
    # different date, different file: no conflict, user-entered date
    r = save(c, upload(c, extra=b"\n%2\n"), report_date="2026-10-01")
    assert r.status_code == 201 and r.json()["date_source"] == "user_entered"


def test_overlap_then_choices(c):
    first = save(c, upload(c)).json()
    rid2 = upload(c, extra=b"\n%2\n")
    r = save(c, rid2)
    assert r.status_code == 409 and r.json()["reason"] == "overlap"
    ov = r.json()["overlaps"]
    ids = [o["test_id"] for o in ov]
    assert "HB" in ids and all(o["existing"] and o["new"] for o in ov)
    assert ov[0]["existing_saved_report_id"] == first["saved_report_id"]
    # partial choice still 409 listing the rest
    r = save(c, rid2, overlap_choice={"HB": "keep_new"})
    assert r.status_code == 409 and "HB" not in [o["test_id"] for o in r.json()["overlaps"]]
    choice = {i: "keep_existing" for i in ids}
    choice["HB"], choice["RBC"] = "keep_new", "keep_both"
    r = save(c, rid2, overlap_choice=choice)
    assert r.status_code == 201, r.text
    new_ids = {t["test_id"] for t in r.json()["tests"]}
    assert new_ids == {"HB", "RBC"}
    pts = c.get("/v1/history/trends?test_id=HB", headers=A).json()["points"]
    assert [p["saved_report_id"] for p in pts] == [r.json()["saved_report_id"]]
    assert len(c.get("/v1/history/trends?test_id=RBC", headers=A).json()["points"]) == 2


def test_trends_api_and_isolation(c):
    sid = save(c, upload(c)).json()["saved_report_id"]
    r = c.get("/v1/history/trends?test_id=HB", headers=A).json()
    p = r["points"][0]
    assert r["test_id"] == "HB" and p["ref"]["low"] == 12.0 and p["unit"] == "g/dL"
    assert set(p) == {"report_date", "saved_report_id", "value", "unit", "ref", "flag",
                      "is_critical", "different_unit"}
    assert c.get("/v1/history/trends", headers=A).json()["reason"] == "invalid_test_id"
    # user B sees and deletes nothing of A's
    assert c.get("/v1/history", headers=B).json()["reports"] == []
    assert c.get("/v1/history/trends?test_id=HB", headers=B).json()["points"] == []
    assert c.delete(f"/v1/history/{sid}", headers=B).status_code == 404
    c.delete("/v1/history", headers=B)
    assert len(c.get("/v1/history", headers=A).json()["reports"]) == 1


def test_delete_one_and_withdraw(c, tmp_path):
    s1 = save(c, upload(c)).json()["saved_report_id"]
    save(c, upload(c, extra=b"\n%2\n"), report_date="2026-10-01")
    assert c.delete(f"/v1/history/{s1}", headers=A).status_code == 204
    assert c.delete(f"/v1/history/{s1}", headers=A).status_code == 404
    assert len(c.get("/v1/history", headers=A).json()["reports"]) == 1
    assert c.delete("/v1/history", headers=A).status_code == 204
    assert c.get("/v1/history", headers=A).json()["reports"] == []
    with sqlite3.connect(tmp_path / "h.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM saved_tests").fetchone()[0] == 0
        rows = db.execute("SELECT notice_version, consented_at, withdrawn_at FROM consents").fetchall()
    assert rows and all(r[0] == "2026-11-v1" and r[1] and r[2] for r in rows)


def test_db_holds_only_allowed_fields(c, tmp_path):
    save(c, upload(c))
    with sqlite3.connect(tmp_path / "h.sqlite") as db:
        cols = {r[1] for r in db.execute("PRAGMA table_info(saved_tests)")}
        rep_cols = {r[1] for r in db.execute("PRAGMA table_info(saved_reports)")}
        dump = "\n".join(db.iterdump())
    assert cols == ALLOWED_TEST_COLS
    assert rep_cols == {"saved_report_id", "user_id", "report_date", "date_source", "file_sha256",
                        "consent_notice_version", "saved_at"}
    for banned in ("HEMOGLOBIN", "TOTAL RBC COUNT", "r.pdf", "%PDF", "@", "source_span"):
        assert banned not in dump, banned
    assert not [p for p in tmp_path.rglob("*") if p.suffix in (".pdf", ".png", ".jpg")]


# ---- store-level ----
def _t(tid, num, unit_raw, low, high, flag="normal", crit=False):
    return {"test_id": tid, "panel": "cbc", "value": {"raw": str(num), "number": num, "comparator": "="},
            "unit_raw": unit_raw, "unit": unit_raw, "ref": {"raw": f"{low}-{high}", "low": low,
                                                             "high": high, "source": "report"},
            "flag": flag, "severity": "critical" if crit else "normal", "is_critical": crit,
            "raw_name": "PATIENT NAME X", "source_span": "secret text"}


def test_trend_units_and_own_ranges(tmp_path):
    h = HistoryStore(tmp_path / "h.sqlite")
    kw = {"date_source": "user_entered", "notice_version": "v1"}
    h.save("u", tests=[_t("PLT", 250, "10^3/uL", 150, 410)], report_date=date(2026, 1, 1), file_sha="a", **kw)
    h.save("u", tests=[_t("PLT", 2.5, "lakhs/cumm", 1.5, 4.0)], report_date=date(2026, 2, 1), file_sha="b", **kw)
    h.save("u", tests=[_t("PLT", 9, "furlongs", 1, 2, "high", True)], report_date=date(2026, 3, 1),
           file_sha="c", **kw)
    p = h.trends("u", "PLT")
    assert [x["report_date"] for x in p] == ["2026-01-01", "2026-02-01", "2026-03-01"]
    assert p[0]["ref"]["high"] == 410 and not p[0]["different_unit"]
    assert p[1]["value"]["number"] == pytest.approx(250) and p[1]["ref"]["high"] == pytest.approx(400)
    assert p[1]["value"]["raw"] == "2.5" and not p[1]["different_unit"]
    assert p[2]["different_unit"] and p[2]["unit"] == "furlongs" and p[2]["is_critical"]
    assert h.trends("other", "PLT") == []
    dump = "\n".join(sqlite3.connect(tmp_path / "h.sqlite").iterdump())
    assert "PATIENT NAME" not in dump and "secret text" not in dump


def test_retention_purge(tmp_path):
    now = [1_000_000_000.0]
    h = HistoryStore(tmp_path / "h.sqlite", clock=lambda: now[0])
    kw = {"date_source": "user_entered", "notice_version": "v1"}
    for u in ("old", "active"):
        h.touch(u)
        h.save(u, tests=[_t("HB", 13, "g/dL", 12, 15)], report_date=date(2026, 1, 1), file_sha=u, **kw)
    now[0] += 200 * 86400
    h.touch("active")
    now[0] += 200 * 86400  # old: 400 days, active: 200 days
    assert h.purge_inactive() == 1
    assert h.list("old") == [] and h.consents("old") == []
    assert len(h.list("active")) == 1
