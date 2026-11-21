"""Opt-in saved history and trends (PLAN.md sections 4.3, 5, 10, 11). No LLM.

SQLite under cache/. Every query is parameterized and scoped by the Google subject ID.
Stored per test: test_id, panel, value, units, range, flag, severity, is_critical. Never the
file, file name, extracted text (source_span, raw_name, remarks), names or email.
"""
from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from lablens import config
from lablens.flag_engine import to_canonical
from lablens.reference import load_tests, load_unit_conversions
from lablens.schemas import FlaggedTest, SavedReport

CHOICES = {"keep_new", "keep_existing", "keep_both"}
TEST_COLS = ("test_id", "panel", "value_raw", "value_number", "comparator", "unit_raw", "unit",
             "ref_raw", "ref_low", "ref_high", "ref_source", "flag", "severity", "is_critical")
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, last_seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS consents (
  user_id TEXT NOT NULL, notice_version TEXT NOT NULL, consented_at TEXT NOT NULL,
  withdrawn_at TEXT);
CREATE TABLE IF NOT EXISTS saved_reports (
  saved_report_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, report_date TEXT NOT NULL,
  date_source TEXT NOT NULL, file_sha256 TEXT NOT NULL, consent_notice_version TEXT NOT NULL,
  saved_at TEXT NOT NULL, UNIQUE (user_id, file_sha256));
CREATE TABLE IF NOT EXISTS saved_tests (
  saved_report_id TEXT NOT NULL REFERENCES saved_reports(saved_report_id) ON DELETE CASCADE,
  user_id TEXT NOT NULL, test_id TEXT NOT NULL, panel TEXT, value_raw TEXT NOT NULL,
  value_number REAL, comparator TEXT NOT NULL, unit_raw TEXT, unit TEXT, ref_raw TEXT NOT NULL,
  ref_low REAL, ref_high REAL, ref_source TEXT NOT NULL, flag TEXT NOT NULL,
  severity TEXT NOT NULL, is_critical INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS saved_tests_user ON saved_tests (user_id, test_id);
"""


class AlreadySaved(Exception):
    def __init__(self, saved_on: date):
        self.saved_on = saved_on


class Overlap(Exception):
    def __init__(self, overlaps: list[dict]):
        self.overlaps = overlaps


def _row_from_test(t: dict) -> tuple:
    v, r = t["value"], t["ref"]
    return (t["test_id"], t.get("panel"), v["raw"], v.get("number"), v.get("comparator", "="),
            t.get("unit_raw"), t.get("unit"), r["raw"], r.get("low"), r.get("high"), r["source"],
            t["flag"], t["severity"], int(bool(t["is_critical"])))


def _test_from_row(row: sqlite3.Row) -> FlaggedTest:
    # Fields not kept (extracted text, page, confidence) get neutral placeholders.
    return FlaggedTest(
        raw_name=row["test_id"], test_id=row["test_id"], panel=row["panel"],
        value={"raw": row["value_raw"], "number": row["value_number"], "comparator": row["comparator"]},
        unit_raw=row["unit_raw"], unit=row["unit"],
        ref={"raw": row["ref_raw"], "low": row["ref_low"], "high": row["ref_high"],
             "source": row["ref_source"]},
        printed_flag=None, remark=None, page=0, source_span="", confidence=1.0,
        flag=row["flag"], severity=row["severity"], is_critical=bool(row["is_critical"]),
        flag_disagrees_with_printed=False)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class HistoryStore:
    def __init__(self, path: Path | str | None = None, clock: Callable[[], float] = time.time):
        self.path = Path(path or config.HISTORY_DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock, self._lock = clock, threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    # ---- sign-in tracking and retention ----
    def touch(self, user_id: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO users (user_id, last_seen) VALUES (?, ?) ON CONFLICT(user_id) "
                      "DO UPDATE SET last_seen = excluded.last_seen", (user_id, self.clock()))

    def purge_inactive(self, days: int = config.HISTORY_RETENTION_DAYS) -> int:
        """Delete everything for users not signed in for `days`. Returns users purged."""
        cutoff = self.clock() - days * 86400
        with self._lock, self._conn() as c:
            users = [r[0] for r in c.execute("SELECT user_id FROM users WHERE last_seen < ?", (cutoff,))]
            for u in users:
                self._delete_user(c, u)
                c.execute("DELETE FROM consents WHERE user_id = ?", (u,))
                c.execute("DELETE FROM users WHERE user_id = ?", (u,))
        return len(users)

    # ---- save ----
    def save(self, user_id: str, *, tests: list[dict], report_date: date, date_source: str,
             file_sha: str, notice_version: str,
             overlap_choice: dict[str, str] | None = None) -> SavedReport:
        tests = [t for t in tests if t.get("test_id")]  # unrecognised rows have no trend identity
        choice = overlap_choice or {}
        with self._lock, self._conn() as c:
            dup = c.execute("SELECT report_date FROM saved_reports WHERE user_id = ? AND file_sha256 = ?",
                            (user_id, file_sha)).fetchone()
            if dup:
                raise AlreadySaved(date.fromisoformat(dup[0]))
            overlaps, by_id = [], {t["test_id"]: t for t in tests}
            for row in c.execute(
                    "SELECT t.*, r.saved_report_id AS sid FROM saved_tests t JOIN saved_reports r "
                    "USING (saved_report_id) WHERE t.user_id = ? AND r.user_id = ? AND r.report_date = ?",
                    (user_id, user_id, report_date.isoformat())):
                if row["test_id"] in by_id:
                    overlaps.append((row, by_id[row["test_id"]]))
            pending = [o for o in overlaps if choice.get(o[0]["test_id"]) not in CHOICES]
            if pending:
                raise Overlap([{"test_id": r["test_id"], "report_date": report_date.isoformat(),
                                "existing_saved_report_id": r["sid"],
                                "existing": _test_from_row(r).model_dump(mode="json"), "new": new}
                               for r, new in pending])
            drop_new = {r["test_id"] for r, _ in overlaps if choice[r["test_id"]] == "keep_existing"}
            for r, _ in overlaps:
                if choice[r["test_id"]] == "keep_new":
                    c.execute("DELETE FROM saved_tests WHERE user_id = ? AND saved_report_id = ? "
                              "AND test_id = ?", (user_id, r["sid"], r["test_id"]))
            sid, saved_at = "sr_" + secrets.token_hex(12), _iso_now()
            c.execute("INSERT INTO saved_reports VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (sid, user_id, report_date.isoformat(), date_source, file_sha,
                       notice_version, saved_at))
            c.executemany(f"INSERT INTO saved_tests (saved_report_id, user_id, {', '.join(TEST_COLS)}) "
                          f"VALUES (?, ?, {', '.join('?' * len(TEST_COLS))})",
                          [(sid, user_id, *_row_from_test(t)) for t in tests
                           if t["test_id"] not in drop_new])
            c.execute("INSERT INTO consents (user_id, notice_version, consented_at) VALUES (?, ?, ?)",
                      (user_id, notice_version, saved_at))
            return self._load(c, user_id, sid)

    # ---- read ----
    def _load(self, c: sqlite3.Connection, user_id: str, sid: str) -> SavedReport:
        r = c.execute("SELECT * FROM saved_reports WHERE user_id = ? AND saved_report_id = ?",
                      (user_id, sid)).fetchone()
        tests = c.execute("SELECT * FROM saved_tests WHERE user_id = ? AND saved_report_id = ? "
                          "ORDER BY rowid", (user_id, sid)).fetchall()
        return SavedReport(saved_report_id=r["saved_report_id"], user_id=r["user_id"],
                           report_date=r["report_date"], date_source=r["date_source"],
                           file_sha256=r["file_sha256"], tests=[_test_from_row(t) for t in tests],
                           consent_notice_version=r["consent_notice_version"], saved_at=r["saved_at"])

    def list(self, user_id: str) -> list[SavedReport]:
        with self._conn() as c:
            ids = [r[0] for r in c.execute("SELECT saved_report_id FROM saved_reports WHERE user_id = ? "
                                           "ORDER BY report_date, saved_at", (user_id,))]
            return [self._load(c, user_id, i) for i in ids]

    def trends(self, user_id: str, test_id: str) -> list[dict]:
        """One point per saved value; exact conversion to the canonical unit, else marked."""
        conv = load_unit_conversions()
        canon = (load_tests().get(test_id) or {}).get("unit")
        with self._conn() as c:
            rows = c.execute(
                "SELECT t.*, r.report_date FROM saved_tests t JOIN saved_reports r USING (saved_report_id) "
                "WHERE t.user_id = ? AND r.user_id = ? AND t.test_id = ? ORDER BY r.report_date, r.saved_at",
                (user_id, user_id, test_id)).fetchall()
        points = []
        for row in rows:
            t = _test_from_row(row)
            num, ok = to_canonical(t.value.number, test_id, t.unit_raw, conv)
            value, ref, unit = t.value.model_dump(), t.ref.model_dump(), t.unit_raw
            if ok:
                lo, _ = to_canonical(t.ref.low, test_id, t.unit_raw, conv)
                hi, _ = to_canonical(t.ref.high, test_id, t.unit_raw, conv)
                value["number"], ref["low"], ref["high"] = num, lo, hi
                unit = canon or t.unit or t.unit_raw
            points.append({"report_date": row["report_date"], "saved_report_id": row["saved_report_id"],
                           "value": value, "unit": unit, "ref": ref, "flag": t.flag.value,
                           "is_critical": t.is_critical, "different_unit": not ok})
        return points

    # ---- delete ----
    @staticmethod
    def _delete_user(c: sqlite3.Connection, user_id: str) -> None:
        c.execute("DELETE FROM saved_tests WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM saved_reports WHERE user_id = ?", (user_id,))

    def delete_one(self, user_id: str, sid: str) -> bool:
        with self._lock, self._conn() as c:
            n = c.execute("DELETE FROM saved_reports WHERE user_id = ? AND saved_report_id = ?",
                          (user_id, sid)).rowcount
            c.execute("DELETE FROM saved_tests WHERE user_id = ? AND saved_report_id = ?", (user_id, sid))
        return n > 0

    def withdraw(self, user_id: str) -> None:
        """Delete all saved reports and mark consent withdrawn (record kept to show later)."""
        with self._lock, self._conn() as c:
            self._delete_user(c, user_id)
            c.execute("UPDATE consents SET withdrawn_at = ? WHERE user_id = ? AND withdrawn_at IS NULL",
                      (_iso_now(), user_id))

    def consents(self, user_id: str) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT notice_version, consented_at, withdrawn_at FROM consents WHERE user_id = ? "
                "ORDER BY rowid", (user_id,))]
