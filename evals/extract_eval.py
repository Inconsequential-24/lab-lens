"""Extraction precision/recall on the 15 SOURCE reports only (never data/reports/eval/).

Calls the pipeline as a black box and scores against data/ground_truth/Dxx.json.
Usage: python evals/extract_eval.py [--no-cache] [--max-inr 20]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lablens import pipeline  # noqa: E402
from lablens.budget import BudgetExceeded, BudgetGuard  # noqa: E402
from lablens.cache import ResponseCache  # noqa: E402

SOURCE_DIR = ROOT / "data" / "reports" / "source"
GT_DIR = ROOT / "data" / "ground_truth"
OUT = ROOT / "evals" / "results_extract_dev.json"


def _unit(u) -> str:
    return "".join((u or "").split()).lower().replace("µ", "u").replace("μ", "u")


def _num_eq(a, b) -> bool:
    return (a is None and b is None) or (a is not None and b is not None and abs(a - b) < 1e-6)


def score_report(gt: dict, pred: dict) -> dict:
    gt_rows = {}
    for t in gt["tests"]:
        gt_rows.setdefault(t["test_id"], []).append(t)
    pred_rows = {}
    for t in pred["tests"]:
        pred_rows.setdefault(t["test_id"], []).append(t)
    n_pred = len(pred["tests"]) + len(pred["unrecognised_tests"])
    tp = value_ok = unit_ok = range_ok = 0
    errors = []
    for tid, gts in gt_rows.items():
        for g, p in zip(gts, pred_rows.get(tid, [])):
            tp += 1
            v = g["value"]["raw"].strip() == p["value"]["raw"].strip() or _num_eq(
                g["value"]["number"], p["value"]["number"])
            u = _unit(g["unit_raw"]) == _unit(p["unit_raw"])
            r = _num_eq(g["ref"]["low"], p["ref"]["low"]) and _num_eq(g["ref"]["high"], p["ref"]["high"])
            value_ok += v
            unit_ok += u
            range_ok += r
            if not (v and u and r):
                errors.append({"test_id": tid, "value_ok": v, "unit_ok": u, "range_ok": r,
                               "gt": [g["value"]["raw"], g["unit_raw"], g["ref"]["raw"]],
                               "pred": [p["value"]["raw"], p["unit_raw"], p["ref"]["raw"]]})
    missed = Counter({k: len(v) for k, v in gt_rows.items()}) - Counter(
        {k: len(v) for k, v in pred_rows.items()})
    return {"gt_rows": len(gt["tests"]), "pred_rows": n_pred, "tp": tp, "value_ok": value_ok,
            "unit_ok": unit_ok, "range_ok": range_ok, "missed": sorted(missed.elements()),
            "unrecognised": pred["unrecognised_tests"], "low_confidence": pred["low_confidence_tests"],
            "status": pred["status"], "warnings": pred["warnings"], "errors": errors,
            "tokens_in": pred["metrics"]["tokens_in"], "tokens_out": pred["metrics"]["tokens_out"],
            "cost_inr": pred["metrics"]["cost_inr"]}


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


async def main(no_cache: bool, max_inr: float) -> dict:
    guard = BudgetGuard()
    start = guard.spent_inr()
    guard = BudgetGuard(guard_inr=min(start + max_inr, guard.guard_inr))
    cache = None if no_cache else ResponseCache()
    per, dropped_by_validate = {}, 0
    for src in sorted(SOURCE_DIR.glob("D*.pdf")):
        gt = json.loads((GT_DIR / f"{src.stem}.json").read_text(encoding="utf-8"))
        try:
            res = await pipeline.run(src, cache=cache, guard=guard)
        except BudgetExceeded as e:
            print(f"ABORT: {e}")
            break
        pred = res.model_dump(mode="json")
        if pred.get("status") == "rejected":
            per[src.stem] = {"rejected": pred["reason"], "gt_rows": len(gt["tests"]), "tp": 0,
                             "pred_rows": 0, "value_ok": 0, "unit_ok": 0, "range_ok": 0,
                             "missed": [t["test_id"] for t in gt["tests"]]}
        else:
            per[src.stem] = score_report(gt, pred)
            dropped_by_validate += sum(int(w.split()[0]) for w in pred["warnings"] if "row(s) dropped" in w)
        print(src.stem, {k: per[src.stem][k] for k in ("gt_rows", "pred_rows", "tp")})
    tot = Counter()
    for r in per.values():
        tot.update({k: r[k] for k in ("gt_rows", "pred_rows", "tp", "value_ok", "unit_ok", "range_ok")})
    summary = {
        "split": "source", "reports": len(per), "gt_rows": tot["gt_rows"], "pred_rows": tot["pred_rows"],
        "matched_rows": tot["tp"], "precision": _ratio(tot["tp"], tot["pred_rows"]),
        "recall": _ratio(tot["tp"], tot["gt_rows"]),
        "value_accuracy": _ratio(tot["value_ok"], tot["tp"]),
        "unit_accuracy": _ratio(tot["unit_ok"], tot["tp"]),
        "range_accuracy": _ratio(tot["range_ok"], tot["tp"]),
        "dropped_rows": tot["gt_rows"] - tot["tp"], "rows_dropped_by_validate": dropped_by_validate,
        "spent_inr_this_run": round(BudgetGuard().spent_inr() - start, 4),
        "tokens_in": sum(r.get("tokens_in", 0) for r in per.values()),
        "tokens_out_incl_thinking": sum(r.get("tokens_out", 0) for r in per.values()),
        "cache": "off" if no_cache else "on",
    }
    out = {"summary": summary, "per_report": per}
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--max-inr", type=float, default=20.0)
    a = ap.parse_args()
    asyncio.run(main(a.no_cache, a.max_inr))
