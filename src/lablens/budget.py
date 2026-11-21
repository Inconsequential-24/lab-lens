"""Budget guard: logs LLM spend in INR and refuses calls that would pass the guard (PLAN.md 8)."""
import sqlite3
import time
from pathlib import Path

from lablens import config


class BudgetExceeded(RuntimeError):
    """Callers catch this and fall back to templates."""


def cost_inr(tokens_in: int, tokens_out: int, tokens_thinking: int = 0) -> float:
    if min(tokens_in, tokens_out, tokens_thinking) < 0:
        raise ValueError("token counts must be non-negative")
    usd = (tokens_in * config.USD_PER_M_INPUT + (tokens_out + tokens_thinking) * config.USD_PER_M_OUTPUT) / 1e6
    return usd * config.INR_PER_USD


class BudgetGuard:
    def __init__(self, path: Path | str | None = None, guard_inr: float | None = None):
        self.path = Path(path or config.BUDGET_DB_PATH)
        self.guard_inr = config.BUDGET_GUARD_INR if guard_inr is None else guard_inr
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS spend (ts REAL, node TEXT, model TEXT, tokens_in INT,"
                " tokens_out INT, tokens_thinking INT, cost_inr REAL, status TEXT)"
            )

    def spent_inr(self) -> float:
        with sqlite3.connect(self.path) as c:
            return c.execute("SELECT COALESCE(SUM(cost_inr), 0) FROM spend").fetchone()[0]

    def allows(self, est_in: int, est_out: int, est_thinking: int = 0) -> bool:
        return self.spent_inr() + cost_inr(est_in, est_out, est_thinking) <= self.guard_inr

    def check(self, est_in: int, est_out: int, est_thinking: int = 0) -> int:
        """Atomically reserve the estimate; returns a reservation id for record()."""
        est = cost_inr(est_in, est_out, est_thinking)
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            c.execute("BEGIN IMMEDIATE")
            spent = c.execute("SELECT COALESCE(SUM(cost_inr), 0) FROM spend").fetchone()[0]
            if spent + est > self.guard_inr:
                c.execute("ROLLBACK")
                raise BudgetExceeded(
                    f"budget guard: spent ₹{spent:.2f}, guard ₹{self.guard_inr:.2f}; using template fallback"
                )
            cur = c.execute(
                "INSERT INTO spend VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), "reservation", config.MODEL_NAME, est_in, est_out, est_thinking, est, "reserved"),
            )
            c.execute("COMMIT")
            return cur.lastrowid
        finally:
            c.close()

    def release(self, reservation: int) -> None:
        """Drop an unused reservation (call failed before any tokens were billed)."""
        with sqlite3.connect(self.path, timeout=30) as c:
            c.execute("DELETE FROM spend WHERE rowid=? AND status='reserved'", (reservation,))

    def record(self, node: str, tokens_in: int, tokens_out: int, tokens_thinking: int = 0,
               status: str = "ok", model: str | None = None, reservation: int | None = None) -> float:
        """Log every call, including failed and retried ones; settles `reservation` if given."""
        cost = cost_inr(tokens_in, tokens_out, tokens_thinking)
        row = (time.time(), node, model or config.MODEL_NAME, tokens_in, tokens_out, tokens_thinking, cost, status)
        with sqlite3.connect(self.path, timeout=30) as c:
            if reservation is not None and c.execute(
                "UPDATE spend SET ts=?, node=?, model=?, tokens_in=?, tokens_out=?, tokens_thinking=?,"
                " cost_inr=?, status=? WHERE rowid=? AND status='reserved'", (*row, reservation)
            ).rowcount:
                return cost
            c.execute("INSERT INTO spend VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
        return cost
