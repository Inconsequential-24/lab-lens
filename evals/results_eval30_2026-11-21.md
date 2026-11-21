# Eval-30 headline: 1 run (mean/spread across runs not available; pooled counts only) (generated from results_eval30.json; do not edit by hand)

Runs completed: 1 of 1; case runs scored: 30; aborted: None; cache: off; model: gemini-3.1-flash-lite

**Excluded (provider_unavailable, not scored): 0 case-runs; per run {1: 0}**

| Family | Metric | Pooled (95% Wilson) | Mean across runs (sd) |
|---|---|---|---|
| Extraction | extraction_precision | 100.0% (251 of 251; CI 98.5%-100.0%) | 100.0% (0.000) |
| Extraction | extraction_recall | 99.6% (251 of 252; CI 97.8%-99.9%) | 99.6% (0.000) |
| Extraction | value_accuracy | 99.6% (250 of 251; CI 97.8%-99.9%) | 99.6% (0.000) |
| Extraction | unit_accuracy | 100.0% (251 of 251; CI 98.5%-100.0%) | 100.0% (0.000) |
| Extraction | range_accuracy | 99.2% (249 of 251; CI 97.1%-99.8%) | 99.2% (0.000) |
| Extraction | name_accuracy | 100.0% (251 of 251; CI 98.5%-100.0%) | 100.0% (0.000) |
| Flags | flag_severity_accuracy_per_test | 99.6% (251 of 252; CI 97.8%-99.9%) | 99.6% (0.000) |
| Flags | flags_all_correct_per_report | 96.7% (29 of 30; CI 83.3%-99.4%) | 96.7% (0.000) |
| Flags | critical_recall | 100.0% (2 of 2; CI 34.2%-100.0%) | 100.0% (0.000) |
| Next step | next_step_and_urgency_accuracy | 100.0% (30 of 30; CI 88.6%-100.0%) | 100.0% (0.000) |
| Next step | rule_accuracy | 100.0% (30 of 30; CI 88.6%-100.0%) | 100.0% (0.000) |
| Safety | grounding_statements | 100.0% (190 of 190; CI 98.0%-100.0%) | 100.0% (0.000) |
| Safety | en_hi_consistency | 100.0% (30 of 30; CI 88.6%-100.0%) | 100.0% (0.000) |
| Safety | unsafe_advice_rate | 0.0% (0 of 30; CI 0.0%-11.3%) | 0.0% (0.000) |
| Safety | fallback_rate | 70.0% (21 of 30; CI 52.1%-83.3%) | 70.0% (0.000) |

| Group | Recall | Flags all-correct | Next step+urgency | Unsafe |
|---|---|---|---|---|
| controlled_variation | 100.0% (65 of 65; CI 94.4%-100.0%) | 100.0% (10 of 10; CI 72.2%-100.0%) | 100.0% (10 of 10; CI 72.2%-100.0%) | 0.0% (0 of 10; CI 0.0%-27.8%) |
| perturbation | 98.8% (83 of 84; CI 93.6%-99.8%) | 87.5% (7 of 8; CI 52.9%-97.8%) | 100.0% (8 of 8; CI 67.6%-100.0%) | 0.0% (0 of 8; CI 0.0%-32.4%) |
| extraction_challenge | 100.0% (52 of 52; CI 93.1%-100.0%) | 100.0% (6 of 6; CI 61.0%-100.0%) | 100.0% (6 of 6; CI 61.0%-100.0%) | 0.0% (0 of 6; CI 0.0%-39.0%) |
| adversarial | 100.0% (51 of 51; CI 93.0%-100.0%) | 100.0% (6 of 6; CI 61.0%-100.0%) | 100.0% (6 of 6; CI 61.0%-100.0%) | 0.0% (0 of 6; CI 0.0%-39.0%) |

Latency per report p50 24322 ms, p95 267699 ms (p95 noisy). Suite spend: ₹12.1575. LLM judge: not run (needs hand labels).
