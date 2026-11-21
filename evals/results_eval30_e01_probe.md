# Eval-30 headline: 1 run (mean/spread across runs not available; pooled counts only) (generated from results_eval30.json; do not edit by hand)

Runs completed: 1 of 1; case runs scored: 1; aborted: None; cache: off; model: gemini-3.1-flash-lite

**Excluded (provider_unavailable, not scored): 0 case-runs; per run {1: 0}**

| Family | Metric | Pooled (95% Wilson) | Mean across runs (sd) |
|---|---|---|---|
| Extraction | extraction_precision | 100.0% (14 of 14; CI 78.5%-100.0%) | 100.0% (0.000) |
| Extraction | extraction_recall | 100.0% (14 of 14; CI 78.5%-100.0%) | 100.0% (0.000) |
| Extraction | value_accuracy | 100.0% (14 of 14; CI 78.5%-100.0%) | 100.0% (0.000) |
| Extraction | unit_accuracy | 100.0% (14 of 14; CI 78.5%-100.0%) | 100.0% (0.000) |
| Extraction | range_accuracy | 100.0% (14 of 14; CI 78.5%-100.0%) | 100.0% (0.000) |
| Extraction | name_accuracy | 100.0% (14 of 14; CI 78.5%-100.0%) | 100.0% (0.000) |
| Flags | flag_severity_accuracy_per_test | 100.0% (14 of 14; CI 78.5%-100.0%) | 100.0% (0.000) |
| Flags | flags_all_correct_per_report | 100.0% (1 of 1; CI 20.6%-100.0%) | 100.0% (0.000) |
| Flags | critical_recall | n/a (0 of 0) | n/a |
| Next step | next_step_and_urgency_accuracy | 100.0% (1 of 1; CI 20.6%-100.0%) | 100.0% (0.000) |
| Next step | rule_accuracy | 100.0% (1 of 1; CI 20.6%-100.0%) | 100.0% (0.000) |
| Safety | grounding_statements | 100.0% (8 of 8; CI 67.6%-100.0%) | 100.0% (0.000) |
| Safety | en_hi_consistency | 100.0% (1 of 1; CI 20.6%-100.0%) | 100.0% (0.000) |
| Safety | unsafe_advice_rate | 0.0% (0 of 1; CI 0.0%-79.3%) | 0.0% (0.000) |
| Safety | fallback_rate | 100.0% (1 of 1; CI 20.6%-100.0%) | 100.0% (0.000) |

| Group | Recall | Flags all-correct | Next step+urgency | Unsafe |
|---|---|---|---|---|
| controlled_variation | 100.0% (14 of 14; CI 78.5%-100.0%) | 100.0% (1 of 1; CI 20.6%-100.0%) | 100.0% (1 of 1; CI 20.6%-100.0%) | 0.0% (0 of 1; CI 0.0%-79.3%) |
| perturbation | n/a (0 of 0) | n/a (0 of 0) | n/a (0 of 0) | n/a (0 of 0) |
| extraction_challenge | n/a (0 of 0) | n/a (0 of 0) | n/a (0 of 0) | n/a (0 of 0) |
| adversarial | n/a (0 of 0) | n/a (0 of 0) | n/a (0 of 0) | n/a (0 of 0) |

Latency per report p50 9860 ms, p95 9860 ms (p95 noisy). Suite spend: ₹0.2713. LLM judge: not run (needs hand labels).
