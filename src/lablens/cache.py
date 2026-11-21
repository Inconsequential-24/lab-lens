"""SQLite response cache keyed by file SHA-256 plus per-node pipeline_version (PLAN.md 9.1)."""
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping

from lablens import config

REPORT_NODE = "report"


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pipeline_version(components: Mapping[str, Any], upstream: str | None = None) -> str:
    """Hash of a node's prompt hash, model, glossary version, thresholds, chained to upstream."""
    payload = json.dumps({"c": components, "up": upstream}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def build_prompt(static_parts: Mapping[str, str], report_content: str) -> str:
    """Static prefix first in fixed order, per-report content last (section 9.2)."""
    prefix = [static_parts[k] for k in config.PROMPT_PREFIX_ORDER if static_parts.get(k)]
    return "\n\n".join([*prefix, report_content])


class ResponseCache:
    def __init__(self, path: Path | str | None = None, ttl_seconds: float | None = None):
        self.path = Path(path or config.RESPONSE_CACHE_PATH)
        self.ttl = ttl_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS responses (file_sha TEXT, node TEXT, version TEXT,"
                " value TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY (file_sha, node, version))"
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def get(self, file_sha: str, node: str, version: str, *, real_upload: bool) -> Any | None:
        if real_upload:
            return None  # section 10: real uploads never touch the response cache
        with self._conn() as c:
            row = c.execute(
                "SELECT value, created FROM responses WHERE file_sha=? AND node=? AND version=?",
                (file_sha, node, version),
            ).fetchone()
        if row is None or (self.ttl is not None and time.time() - row[1] > self.ttl):
            return None
        return json.loads(row[0])

    def put(self, file_sha: str, node: str, version: str, value: Any, *, real_upload: bool) -> bool:
        if real_upload:
            return False
        blob = json.dumps(value)
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?)",
                (file_sha, node, version, blob, time.time()),
            )
        return True

    def clear(self) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM responses")
