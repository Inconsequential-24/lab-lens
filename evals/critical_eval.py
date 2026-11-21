"""Critical-value verification on the HELD-OUT set in data/critical_set (never used for tuning).

(a) flag engine + decision + template fallback + safety_check on every row in rows.json
(b) offline pipeline on the 10 PDFs, extract LLM stubbed from ground truth
(c) --live: real pipeline (live Gemini) once on the 10 PDFs, hard spend cap (--max-inr, default 5)

Usage: python evals/critical_eval.py [--live] [--max-inr 5]
Writes evals/results_critical.json (a live run is merged in under "live").
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from lablens import pipeline  # noqa: E402
from lablens.budget import BudgetExceeded, BudgetGuard  # noqa: E402
from lablens.decision import route_next_step  # noqa: E402
from lablens.flag_engine import flag_test  # noqa: E402
from lablens.safety import safety_check  # noqa: E402
from lablens.schemas import ExtractedTest  # noqa: E402
from lablens.templates import template_fallback, urgent_template  # noqa: E402

SET_DIR = ROOT / "data" / "critical_set"
OUT = ROOT / "evals" / "results_critical.json"
URGENT_PREFIX = {"en": "URGENT:", "hi": "तुरंत ध्यान दें:"}


def wilson(k: int, n: int, z: float = 1.96) -> dict:
    if n == 0:
        return {"k": 0, "n": 0, "rate": None, "ci95": None}
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return {"k": k, "n": n, "rate": round(p, 4), "ci95": [round(max(0, mid - half), 4), round(min(1, mid + half), 4)]}


def urgent_ok(exps, tests) -> bool:
    by = {e.language: e for e in exps}
    return all(l in by and by[l].urgent_message and by[l].urgent_message == urgent_template(l, tests)
               and by[l].urgent_message.startswith(URGENT_PREFIX[l]) for l in ("en", "hi"))


def eval_row(row: dict) -> dict:
    ft = flag_test(ExtractedTest(**row["test"]))
    rec = route_next_step([ft])
    exps = template_fallback([ft], rec)
    fails = safety_check(exps, [ft], rec)
    return {"id": row["id"], "category": row["category"], "expected_critical": row["expected_is_critical"],
            "got_critical": ft.is_critical, "flag_ok": ft.flag.value == row["expected_flag"],
            "got_flag": ft.flag.value, "rule": rec.rule_id, "urgent_ok": urgent_ok(exps, [ft]),
            "no_urgent_when_not_critical": all(not e.urgent_message for e in exps),
            "safety_ok": not fails, "safety_codes": sorted({f.code for f in fails}),
            "warnings": ft.warnings}


def summarise(res: list[dict]) -> dict:
    crit = [r for r in res if r["expected_critical"]]
    non = [r for r in res if not r["expected_critical"]]
    tp = sum(r["got_critical"] for r in crit)
    fp = sum(r["got_critical"] for r in non)
    return {
        "n": len(res), "n_critical": len(crit), "n_noncritical": len(non),
        "critical_recall": wilson(tp, len(crit)),
        "critical_precision": wilson(tp, tp + fp),
        "false_critical_rate_on_noncritical": wilson(fp, len(non)),
        "r1_routing_on_critical": wilson(sum(r["rule"] == "R1_critical" for r in crit), len(crit)),
        "r1_on_noncritical": wilson(sum(r["rule"] == "R1_critical" for r in non), len(non)),
        "urgent_template_first_en_hi_on_critical": wilson(sum(r["urgent_ok"] for r in crit), len(crit)),
        "no_urgent_text_on_noncritical": wilson(sum(r["no_urgent_when_not_critical"] for r in non), len(non)),
        "safety_check_pass": wilson(sum(r["safety_ok"] for r in res), len(res)),
        "expected_flag_match": wilson(sum(r["flag_ok"] for r in res), len(res)),
    }


def part_a(rows: list[dict]) -> dict:
    res = [eval_row(r) for r in rows]
    by_cat = defaultdict(list)
    for r in res:
        by_cat[r["category"]].append(r)
    misses = [r for r in res if r["expected_critical"] != r["got_critical"]
              or (r["expected_critical"] and (r["rule"] != "R1_critical" or not r["urgent_ok"]))
              or not r["safety_ok"]]
    flag_mismatch = [{"id": r["id"], "category": r["category"], "got_flag": r["got_flag"]}
                     for r in res if not r["flag_ok"]]
    return {"overall": summarise(res), "by_category": {c: summarise(v) for c, v in sorted(by_cat.items())},
            "failures": misses, "flag_mismatches": flag_mismatch}


def _gt(cid: str) -> dict:
    return json.loads((SET_DIR / "ground_truth" / f"{cid}.json").read_text(encoding="utf-8"))


def score_pdf(cid: str, gt: dict, r) -> dict:
    if not hasattr(r, "tests"):
        return {"id": cid, "status": "rejected", "reason": getattr(r, "reason", None), "ok": False}
    want = [t["test_id"] for t in gt["tests"] if t["is_critical"]]
    got = {t.test_id for t in r.tests if t.is_critical}
    per = {tid: {"extracted": any(t.test_id == tid for t in r.tests), "flagged_critical": tid in got}
           for tid in want}
    langs = {e.language: e for e in r.explanations}
    urgent = all(langs.get(l) and langs[l].urgent_message for l in ("en", "hi"))
    ok = all(v["flagged_critical"] for v in per.values()) and r.recommendation.rule_id == "R1_critical" and urgent
    return {"id": cid, "status": r.status, "critical": per, "rule": r.recommendation.rule_id,
            "urgent_en_hi": urgent, "false_criticals": sorted(got - set(want)),
            "tokens_in": r.metrics.tokens_in, "tokens_out": r.metrics.tokens_out,
            "cost_inr": round(r.metrics.cost_inr, 4), "warnings": r.warnings, "ok": ok}


def part_b(pdf_ids: list[str]) -> dict:
    os.chdir(ROOT)  # tests/test_pipeline.py opens its ground truth by relative path
    from tests import test_pipeline as tp  # reuse its ground-truth Stub
    import inspect
    from lablens.extract import NoOutput, Usage

    async def no_llm(*_a, **_k):  # offline: any LLM explain step falls back to templates
        raise NoOutput(Usage())

    extra = {"explain_caller": no_llm} if "explain_caller" in inspect.signature(pipeline.run).parameters else {}
    out = []
    with tempfile.TemporaryDirectory() as d:
        for cid in pdf_ids:
            tp.GT = _gt(cid)
            r = asyncio.run(pipeline.run(SET_DIR / "reports" / f"{cid}.pdf", caller=tp.Stub(),
                                         guard=BudgetGuard(Path(d) / f"{cid}.sqlite"), **extra))
            out.append(score_pdf(cid, tp.GT, r))
    return {"pdfs": out, "all_ok": wilson(sum(p["ok"] for p in out), len(out))}


def part_c(pdf_ids: list[str], max_inr: float) -> dict:
    base = BudgetGuard()
    start = base.spent_inr()
    guard = BudgetGuard(guard_inr=min(start + max_inr, base.guard_inr))
    out, aborted = [], None
    for cid in pdf_ids:
        try:
            r = asyncio.run(pipeline.run(SET_DIR / "reports" / f"{cid}.pdf", real_upload=True,
                                         guard=guard))
        except BudgetExceeded as e:
            aborted = f"{cid}: {e}"
            break
        out.append(score_pdf(cid, _gt(cid), r))
        if any("budget" in w.lower() for w in getattr(r, "warnings", [])):
            aborted = f"{cid}: budget guard engaged"
            break
        if guard.spent_inr() - start >= max_inr:
            aborted = f"after {cid}: spend cap reached"
            break
    return {"pdfs": out, "all_ok": wilson(sum(p["ok"] for p in out), len(out)),
            "spent_inr": round(guard.spent_inr() - start, 4), "cap_inr": max_inr, "aborted": aborted,
            "tokens_in": sum(p.get("tokens_in", 0) for p in out),
            "tokens_out": sum(p.get("tokens_out", 0) for p in out)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="run the real pipeline once (spends money)")
    ap.add_argument("--max-inr", type=float, default=5.0)
    args = ap.parse_args()
    data = json.loads((SET_DIR / "rows.json").read_text(encoding="utf-8"))
    pdf_ids = [p["id"] for p in data["pdfs"]]
    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    if args.live:
        result = {**prev, "live": part_c(pdf_ids, args.max_inr)}
    else:
        result = {"held_out": True, "set": {k: data[k] for k in ("n_rows", "n_critical", "counts_by_category")},
                  "rows": part_a(data["rows"]), "offline_pipeline": part_b(pdf_ids),
                  **({"live": prev["live"]} if "live" in prev else {})}
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    view = result["live"] if args.live else {"rows": result["rows"]["overall"],
                                             "pdf_all_ok": result["offline_pipeline"]["all_ok"]}
    print(json.dumps(view, indent=1, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    main()
