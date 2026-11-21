"""Explanation dev run on the 15 SOURCE reports only (never data/reports/eval/ or critical sets).

Records per report: safety pass/fail, retries, fallback, tokens per node, latency, INR.
A BudgetGuard caps this run's spend at --max-inr above what is already logged.
Usage: python evals/explain_dev.py [--max-inr 10] [--no-cache]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lablens import pipeline  # noqa: E402
from lablens.budget import BudgetGuard  # noqa: E402
from lablens.cache import ResponseCache  # noqa: E402

SOURCE_DIR = ROOT / "data" / "reports" / "source"
OUT = ROOT / "evals" / "results_explain_dev.json"
NODES = ("extract", "plan_statements", "render_en", "render_hi")


async def one(path: Path, guard: BudgetGuard, cache) -> dict:
    state: dict = {}
    t0 = time.perf_counter()
    r = await pipeline.run(path, cache=cache, guard=guard, state_out=state)
    row = {"report": path.stem, "wall_ms": round((time.perf_counter() - t0) * 1000)}
    if r.status == "rejected":
        return {**row, "rejected": r.reason}
    sources = sorted({e.source for e in r.explanations})
    return {**row, "status": r.status, "explanation_source": sources,
            "safety_pass_llm": sources == ["llm"],
            "fallback_used": "template_fallback" in sources,
            "fallback_reason": state.get("fallback_reason"),
            "retries": r.metrics.retries, "plan_attempts": state.get("plan_attempts"),
            "render_attempts": {l: state.get(f"render_attempts_{l}") for l in ("en", "hi")},
            "safety_failures_per_round": state.get("safety_codes") or [],
            "tokens": {n: state.get(f"usage_{n}") for n in NODES},
            "latency_ms": {k: round(v) for k, v in r.metrics.latency_ms.items()},
            "cost_inr": round(r.metrics.cost_inr, 4),
            "explanations": [e.model_dump(mode="json") for e in r.explanations]}


async def main(max_inr: float, no_cache: bool, pace_s: float) -> None:
    probe = BudgetGuard()
    start = probe.spent_inr()
    guard = BudgetGuard(guard_inr=start + max_inr)  # hard cap for this run
    cache = None if no_cache else ResponseCache()
    rows = []
    for i, p in enumerate(sorted(SOURCE_DIR.glob("D*.pdf"))):
        if i:
            await asyncio.sleep(pace_s)  # free-tier key: 15 requests/minute
        try:
            rows.append(await one(p, guard, cache))
        except Exception as e:  # record and continue; one report must not lose the run
            rows.append({"report": p.stem, "error": f"{type(e).__name__}: {str(e)[:200]}"})
        print(p.stem, rows[-1].get("explanation_source"), rows[-1].get("retries"),
              rows[-1].get("cost_inr"), flush=True)
    done = [r for r in rows if "rejected" not in r and "error" not in r]
    agg = {}
    for n in NODES:
        us = [r["tokens"][n] for r in done if r["tokens"].get(n) and r["tokens"][n]["calls"]]
        if us:
            calls = sum(u["calls"] for u in us)
            agg[n] = {"calls": calls,
                      **{k: round(sum(u[k] for u in us) / calls) for k in
                         ("tokens_in", "tokens_out", "tokens_thinking", "tokens_cached")}}
    summary = {"reports": len(rows), "rejected": sum("rejected" in r for r in rows),
               "errors": sum("error" in r for r in rows),
               "safety_pass_rate_llm": sum(r["safety_pass_llm"] for r in done) / max(len(done), 1),
               "fallback_rate": sum(r["fallback_used"] for r in done) / max(len(done), 1),
               "total_retries": sum(r["retries"] for r in done),
               "avg_tokens_per_call": agg,
               "spent_inr_this_run": round(BudgetGuard().spent_inr() - start, 4),
               "cache": "off" if no_cache else "on (extract may be warm)"}
    OUT.write_text(json.dumps({"summary": summary, "per_report": rows}, ensure_ascii=False,
                              indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-inr", type=float, default=10.0)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--pace", type=float, default=25.0, help="seconds between reports")
    a = ap.parse_args()
    asyncio.run(main(a.max_inr, a.no_cache, a.pace))
