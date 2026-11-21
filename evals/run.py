"""Scored evaluation of the 30 frozen eval cases E01-E30 (PLAN.md section 7, milestone 9).

Real Gemini, response cache OFF (cold), BudgetGuard hard cap. Each case is run --runs times.
Results are read-only with respect to data/ and prompts: this script writes only --out and
the matching .md headline table. The LLM judge needs hand labels and is recorded as not run.
Usage: python evals/run.py [--runs 3] [--cases E01,E02] [--max-inr 80] [--out ...] [--pace-rpm 12]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from evals.extract_eval import score_report  # noqa: E402
from evals.ml_eval import wilson  # noqa: E402
from lablens import config, pipeline  # noqa: E402
from lablens.budget import BudgetExceeded, BudgetGuard  # noqa: E402
from lablens.extract import version as extract_version  # noqa: E402
from lablens.safety import safety_check  # noqa: E402
from lablens.schemas import Explanation, FlaggedTest, Recommendation  # noqa: E402

GT_DIR = ROOT / "data" / "ground_truth"
OUT = ROOT / "evals" / "results_eval30.json"
GROUPS = ("controlled_variation", "perturbation", "extraction_challenge", "adversarial")
NODES = ("extract", "plan_statements", "render_en", "render_hi")
GROUNDING = {"missing_citation", "unknown_citation", "glossary_flag_mismatch", "ungrounded_number",
             "missing_unit", "wrong_direction", "mixed_direction",
             "negated_direction", "reassurance_against_flag"}
CONSISTENCY = {"claim_set_mismatch", "citation_mismatch", "number_mismatch", "missing_language"}
UNSAFE = {"banned_phrase"}
BACKOFF_S = (30, 60, 120)  # whole-case retries on provider outages (<= 3.5 min waiting per case)


def _provider_error(msg: str) -> bool:
    return any(k in msg for k in ("ServerError", "503", "500", "502", "504", "UNAVAILABLE",
                                  "RESOURCE_EXHAUSTED", "429", "provider_unavailable",
                                  "ProviderUnavailable", "DynamicNodeFailError"))
# Pooled count metrics: name -> (numerator key, denominator key) in the per-case score.
RATES = {
    "extraction_precision": ("tp", "pred_rows"), "extraction_recall": ("tp", "gt_rows"),
    "value_accuracy": ("value_ok", "tp"), "unit_accuracy": ("unit_ok", "tp"),
    "range_accuracy": ("range_ok", "tp"), "name_accuracy": ("name_ok", "tp"),
    "flag_accuracy_per_test": ("flag_ok", "gt_rows"),
    "flag_severity_accuracy_per_test": ("flag_sev_ok", "gt_rows"),
    "flags_all_correct_per_report": ("report_flags_ok", "reports"),
    "critical_recall": ("critical_found", "critical_gt"),
    "next_step_accuracy": ("next_step_ok", "reports"), "urgency_accuracy": ("urgency_ok", "reports"),
    "next_step_and_urgency_accuracy": ("next_urg_ok", "reports"), "rule_accuracy": ("rule_ok", "reports"),
    "grounding_statements": ("grounded_statements", "statements"),
    "grounding_reports": ("grounded_reports", "shown_reports"),
    "en_hi_consistency": ("consistent_reports", "shown_reports"),
    "unsafe_advice_rate": ("unsafe_reports", "reports"),
    "fallback_rate": ("fallback_reports", "reports"),
    "explanation_withheld_rate": ("withheld_reports", "reports"),
    "safety_pass_first_try": ("first_try_pass", "reports"),
}


def _name(s) -> str:
    return " ".join((s or "").lower().replace(".", " ").split())


def load_gt(case_id: str) -> dict:
    return json.loads((GT_DIR / f"{case_id}.json").read_text(encoding="utf-8"))


def score_case(gt: dict, r) -> dict:
    """Score one ReportResult (or Rejected) against frozen ground truth and expectations."""
    exp = gt["expected"]
    n_crit = sum(t["is_critical"] for t in gt["tests"])
    base = {"reports": 1, "gt_rows": len(gt["tests"]), "critical_gt": n_crit}
    if r.status == "rejected":
        return {**base, "rejected": r.reason, "pred_rows": 0, "tp": 0, "unsafe_reports": 0,
                "fallback_reports": 0}
    pred = r.model_dump(mode="json")
    s = score_report(gt, pred)
    # A correctly listed unsupported test (ground truth unrecognised_tests) is not an invented row.
    gt_unrec = {_name(u) for u in gt.get("unrecognised_tests", [])}
    s["pred_rows"] -= sum(_name(u) in gt_unrec for u in pred["unrecognised_tests"])
    by_pred: dict = {}
    for t in pred["tests"]:
        by_pred.setdefault(t["test_id"], []).append(t)
    by_gt: dict = {}
    for t in gt["tests"]:
        by_gt.setdefault(t["test_id"], []).append(t)
    name_ok = flag_ok = flag_sev_ok = crit_found = 0
    flag_errors = []
    for tid, gts in by_gt.items():
        for g, p in zip(gts, by_pred.get(tid, [])):
            name_ok += _name(g["printed_name"]) == _name(p["raw_name"])
            f = p["flag"] == g["expected_flag"]
            fs = f and p["severity"] == g["expected_severity"]
            flag_ok += f
            flag_sev_ok += fs
            crit_found += g["is_critical"] and p["is_critical"]
            if not fs:
                flag_errors.append({"test_id": tid, "expected": [g["expected_flag"], g["expected_severity"]],
                                    "got": [p["flag"], p["severity"]]})
    rec = r.recommendation
    ns, urg, rule = rec.next_step == exp["next_step"], rec.urgency == exp["urgency"], rec.rule_id == exp["rule"]
    # Safety on the FINAL shown text (after retries / fallback / withholding).
    exps, tests = r.explanations, r.tests
    shown = bool(exps)
    fails = safety_check(exps, tests, rec) if shown else []
    codes = sorted({f.code for f in fails})
    bad_claims = {(f.language, f.claim_id) for f in fails if f.code in GROUNDING and f.claim_id}
    summary_bad = any(f.code in GROUNDING and not f.claim_id for f in fails)
    stmts = [(e.language, st.claim_id) for e in exps for st in e.statements]
    sources = sorted({e.source for e in exps})
    return {**base, **{k: s[k] for k in ("pred_rows", "tp", "value_ok", "unit_ok", "range_ok")},
            "name_ok": name_ok, "flag_ok": flag_ok, "flag_sev_ok": flag_sev_ok,
            "report_flags_ok": int(flag_sev_ok == len(gt["tests"]) and s["tp"] == len(gt["tests"])),
            "critical_found": crit_found, "next_step_ok": int(ns), "urgency_ok": int(urg),
            "next_urg_ok": int(ns and urg), "rule_ok": int(rule),
            "statements": len(stmts), "grounded_statements": sum(x not in bad_claims for x in stmts),
            "shown_reports": int(shown),
            "grounded_reports": int(shown and not bad_claims and not summary_bad),
            "consistent_reports": int(shown and not any(f.code in CONSISTENCY for f in fails)),
            "unsafe_reports": int(any(f.code in UNSAFE for f in fails)),
            "fallback_reports": int("template_fallback" in sources or not shown),
            "withheld_reports": int(not shown),
            "got": {"next_step": rec.next_step, "urgency": rec.urgency, "rule": rec.rule_id},
            "expected": {k: exp[k] for k in ("next_step", "urgency", "rule")},
            "missed_rows": s["missed"], "field_errors": s["errors"], "flag_errors": flag_errors,
            "final_safety_codes": codes, "explanation_source": sources, "status": r.status,
            "warnings": r.warnings}


def _rate_block(rows: list[dict]) -> dict:
    tot = Counter()
    for r in rows:
        tot.update({k: v for k, v in r.items() if isinstance(v, int) and not isinstance(v, bool)})
    return {m: wilson(int(tot[a]), int(tot[b])) for m, (a, b) in RATES.items()}


def _pct(xs: list[float], q: float):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))], 1)


def aggregate(results: list[dict]) -> dict:
    """results: per run x case rows with 'run', 'case', 'group', 'score', timing/usage fields."""
    scored = [x for x in results if "score" in x]
    runs = sorted({x["run"] for x in scored})
    per_run = {r: _rate_block([x["score"] for x in scored if x["run"] == r]) for r in runs}
    across = {}
    for m in RATES:
        vals = [per_run[r][m]["rate"] for r in runs if per_run[r][m]["rate"] is not None]
        across[m] = {"mean": round(statistics.mean(vals), 4) if vals else None,
                     "sd": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0 if vals else None,
                     "min": min(vals) if vals else None, "max": max(vals) if vals else None}
    groups = {g: _rate_block([x["score"] for x in scored if x["group"] == g]) for g in GROUPS}
    wall = [x["wall_ms"] for x in scored]
    node_ms = {n: [x["latency_ms"][n] for x in scored if n in x.get("latency_ms", {})]
               for n in (*NODES, "safety_check")}
    tok = Counter()
    for x in results:
        for n, u in (x.get("tokens") or {}).items():
            if u:
                tok.update({f"{n}.{k}": u.get(k, 0) for k in
                            ("calls", "tokens_in", "tokens_out", "tokens_thinking", "tokens_cached")})
    costs = [x["cost_inr"] for x in scored]
    return {"per_run": per_run, "across_runs": across,
            "pooled": _rate_block([x["score"] for x in scored]), "per_group_pooled": groups,
            "latency_ms": {"note": "p95 on <=90 samples is noisy",
                           "per_report": {"p50": _pct(wall, .5), "p95": _pct(wall, .95)},
                           "per_node": {n: {"p50": _pct(v, .5), "p95": _pct(v, .95), "n": len(v)}
                                        for n, v in node_ms.items() if v}},
            "cost": {"per_report_mean_inr": round(statistics.mean(costs), 4) if costs else None,
                     "per_report_max_inr": round(max(costs), 4) if costs else None,
                     "tokens_by_node": dict(sorted(tok.items()))},
            "llm_judge": "not run (needs hand labels)", "judge_agreement": "not run (needs hand labels)"}


def _fmt(b: dict) -> str:
    if b["rate"] is None:
        return "n/a (0 of 0)"
    return f"{b['rate']:.1%} ({b['k']} of {b['n']}; CI {b['ci95'][0]:.1%}-{b['ci95'][1]:.1%})"


def headline_md(out: dict) -> str:
    a, p = out["aggregate"]["across_runs"], out["aggregate"]["pooled"]
    rows = [("Extraction", "extraction_precision"), ("Extraction", "extraction_recall"),
            ("Extraction", "value_accuracy"), ("Extraction", "unit_accuracy"),
            ("Extraction", "range_accuracy"), ("Extraction", "name_accuracy"),
            ("Flags", "flag_severity_accuracy_per_test"), ("Flags", "flags_all_correct_per_report"),
            ("Flags", "critical_recall"), ("Next step", "next_step_and_urgency_accuracy"),
            ("Next step", "rule_accuracy"), ("Safety", "grounding_statements"),
            ("Safety", "en_hi_consistency"), ("Safety", "unsafe_advice_rate"),
            ("Safety", "fallback_rate")]
    s = out["summary"]
    lines = [f"# Eval-30 headline: {s['runs_label']} (generated from results_eval30.json; "
             "do not edit by hand)", "",
             f"Runs completed: {s['runs_completed']} of {s['runs_requested']}; case runs scored: "
             f"{s['case_runs_scored']}; aborted: {s['aborted']}; cache: off; model: {s['model']}", "",
             f"**Excluded (provider_unavailable, not scored): {s['excluded_provider_unavailable']['total']} "
             f"case-runs; per run {s['excluded_provider_unavailable']['per_run']}**", "",
             "| Family | Metric | Pooled (95% Wilson) | Mean across runs (sd) |", "|---|---|---|---|"]
    for fam, m in rows:
        mean, sd = a[m]["mean"], a[m]["sd"]
        spread = "n/a" if mean is None else f"{mean:.1%} ({sd:.3f})"
        lines.append(f"| {fam} | {m} | {_fmt(p[m])} | {spread} |")
    lines += ["", "| Group | Recall | Flags all-correct | Next step+urgency | Unsafe |", "|---|---|---|---|---|"]
    for g, b in out["aggregate"]["per_group_pooled"].items():
        lines.append(f"| {g} | {_fmt(b['extraction_recall'])} | {_fmt(b['flags_all_correct_per_report'])} | "
                     f"{_fmt(b['next_step_and_urgency_accuracy'])} | {_fmt(b['unsafe_advice_rate'])} |")
    lat = out["aggregate"]["latency_ms"]["per_report"]
    lines += ["", f"Latency per report p50 {lat['p50']} ms, p95 {lat['p95']} ms (p95 noisy). "
              f"Suite spend: ₹{s['spent_inr']:.4f}. LLM judge: not run (needs hand labels).", ""]
    return "\n".join(lines)


async def one(case_id: str, run_i: int, guard, caller, explain_caller) -> dict:
    gt = load_gt(case_id)
    state: dict = {}
    t0 = time.perf_counter()
    row = {"run": run_i, "case": case_id, "group": gt["variation"]}
    try:
        r = await pipeline.run(ROOT / gt["input"], cache=None, guard=guard, caller=caller,
                               explain_caller=explain_caller, state_out=state)
    except BudgetExceeded as e:
        return {**row, "budget_abort": str(e)}
    row.update(wall_ms=round((time.perf_counter() - t0) * 1000),
               tokens={n: state.get(f"usage_{n}") for n in NODES})
    if r.status == "rejected" and r.reason == "budget_exhausted" or \
            "budget guard" in (state.get("fallback_reason") or ""):
        return {**row, "budget_abort": state.get("fallback_reason") or r.reason}
    if r.status == "rejected" and r.reason == "provider_unavailable":
        return {**row, "provider_error": "rejected: provider_unavailable"}
    calls = sum((u or {}).get("calls", 0) for u in row["tokens"].values())
    return {**row, "score": score_case(gt, r), "calls": calls,
            "latency_ms": {k: round(v) for k, v in getattr(r, "metrics", None).latency_ms.items()}
            if r.status != "rejected" else {},
            "cost_inr": round(r.metrics.cost_inr, 4) if r.status != "rejected" else 0.0,
            "retries": r.metrics.retries if r.status != "rejected" else 0,
            "fallback_reason": state.get("fallback_reason"),
            "safety_codes_per_round": state.get("safety_codes") or []}


async def main(runs: int = 3, cases: list[str] | None = None, max_inr: float = 80.0,
               out_path: Path = OUT, pace_rpm: float = 12.0, guard: BudgetGuard | None = None,
               caller=None, explain_caller=None, backoff_scale: float = 1.0) -> dict:
    cases = cases or sorted(p.stem for p in GT_DIR.glob("E*.json"))
    probe = guard or BudgetGuard()
    start = probe.spent_inr()
    guard = BudgetGuard(probe.path, guard_inr=start + max_inr)  # hard cap for this suite
    t_suite = time.perf_counter()
    results, aborted = [], None
    for run_i in range(1, runs + 1):
        for cid in cases:
            t0 = time.perf_counter()
            for attempt in range(len(BACKOFF_S) + 1):
                try:
                    x = await one(cid, run_i, guard, caller, explain_caller)
                except Exception as e:  # record and continue: one case must not lose the suite
                    x = {"run": run_i, "case": cid, "group": load_gt(cid)["variation"],
                         "error": f"{type(e).__name__}: {str(e)[:300]}"}
                    if _provider_error(x["error"]):
                        x["provider_error"] = x.pop("error")
                x["attempts"] = attempt + 1
                if "provider_error" not in x or attempt == len(BACKOFF_S):
                    break
                print(run_i, cid, "provider error; retrying in", BACKOFF_S[attempt], "s", flush=True)
                await asyncio.sleep(BACKOFF_S[attempt] * backoff_scale)
            if "provider_error" in x:
                x["status"] = "provider_unavailable"  # excluded from every rate denominator
            results.append(x)
            print(run_i, cid, x.get("score", {}).get("next_urg_ok"), x.get("cost_inr"),
                  x.get("error") or x.get("budget_abort") or "", flush=True)
            if "budget_abort" in x:
                aborted = {"run": run_i, "case": cid, "reason": x["budget_abort"]}
                break
            if pace_rpm > 0:  # free-tier key: pace by LLM calls made
                wait = x.get("calls", 4) * 60.0 / pace_rpm - (time.perf_counter() - t0)
                if wait > 0:
                    await asyncio.sleep(wait)
        if aborted:
            break
    scored = [x for x in results if "score" in x]
    full_runs = sum(sum(1 for x in scored if x["run"] == r) == len(cases) for r in range(1, runs + 1))
    label = f"{runs} run" + ("s" if runs > 1 else "") + \
        ("" if runs > 1 else " (mean/spread across runs not available; pooled counts only)")
    out = {"summary": {"runs_label": label, "runs_requested": runs, "cases": cases, "runs_completed": full_runs,
                       "case_runs_scored": len(scored), "errors": sum("error" in x for x in results),
                       "excluded_provider_unavailable": {
                           "total": sum("provider_error" in x for x in results),
                           "per_run": {r: sum("provider_error" in x and x["run"] == r for x in results)
                                       for r in range(1, runs + 1)},
                           "cases": [f"run{x['run']}:{x['case']}" for x in results if "provider_error" in x],
                           "note": "Gemini 5xx/429 after 3 whole-case retries; not scored, "
                                   "excluded from all denominators"},
                       "aborted": aborted, "max_inr": max_inr,
                       "spent_inr": round(guard.spent_inr() - start, 4),
                       "runtime_s": round(time.perf_counter() - t_suite, 1),
                       "model": config.MODEL_NAME, "extract_prompt_version": extract_version(),
                       "rates_usd_per_m": [config.USD_PER_M_INPUT, config.USD_PER_M_OUTPUT],
                       "inr_per_usd": config.INR_PER_USD, "cache": "off (cold)",
                       "paid_tier_key": config.PAID_TIER_KEY},
           "aggregate": aggregate(results), "per_case_run": results}
    out_path = Path(out_path)
    out_path.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    out_path.with_suffix(".md").write_text(headline_md(out), encoding="utf-8")
    print(json.dumps(out["summary"], indent=1, default=str))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--cases", default="", help="comma-separated ids; default all E*")
    ap.add_argument("--max-inr", type=float, default=80.0)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--pace-rpm", type=float, default=12.0)
    a = ap.parse_args()
    if a.runs < 1 or a.max_inr <= 0:
        ap.error("--runs must be >= 1 and --max-inr > 0")
    ids = [c.strip() for c in a.cases.split(",") if c.strip()] or None
    if ids and any(not (GT_DIR / f"{c}.json").exists() or not c.startswith("E") for c in ids):
        ap.error("unknown or non-eval case id")
    asyncio.run(main(a.runs, ids, a.max_inr, a.out, a.pace_rpm))
