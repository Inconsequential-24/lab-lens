# AI_USAGE.md

How AI tools were used in this project, and what I did myself.

## Tools
| Tool | Used for |
|---|---|
| Claude (Anthropic) | Planning and review of PLAN.md; the synthetic report generator (`scripts/generate_reports.py`), its 15 source-report and 30 derived eval-case specs, and tests; the ADK 2.0 spike (`spikes/adk/`); drafting this file |
| Claude Code with specialised subagents (planning, implementation, review, verification, documentation) | Built the generator, the pipeline, the ML nodes, the API and the frontend, and the README draft, under my direction and with my approval at each stage |
| Replit (AI agent) | Fast prototyping of the web UI and a first rule-based flow, used to explore layout and screens quickly |
| Google Gemini (runtime) | The LLM nodes inside the pipeline (extraction and explanations), as described in PLAN.md. Actual spend is in the README |

## Design inspiration
- **Replit**: the first interactive prototype of the report screen, demo-report list, language
  toggle and persistent "not a diagnosis" banner.
- **Figma Community**: visual inspiration for layout and styling of health and report pages.
- The final UI is built from the provided design reference, `docs/ui/LabLens-Understand-your-report.png`.

## What the AI produced vs. what I decided
- I set the product direction: rules for flags with the LLM explaining like a lab technician,
  confidence and severity scores, trained ML nodes, caching, the consented real-upload
  feature, and which experiments to include.
- Claude drafted PLAN.md, the generator and the spike from those decisions; I reviewed and
  directed the changes. Code from AI tools was run and tested before being relied on (generator
  tests, spike tests). Reference ranges, critical thresholds and LOINC codes are demo values,
  not clinician-reviewed.
- Claude Code subagents then built the pipeline, ML nodes, API and frontend from the approved
  plan. Independent review passes found and fixed real issues, including: a critical-value
  check that ignored units, safety-check bypasses, PII leaks in redaction, and a race in the
  budget guard. Tests and evals were run before results were relied on.
- Hindi text (explanations, glossary, interface text and the consent notice) was model-written;
  I reviewed it by hand on 2026-11-21. It is not reviewed by a clinician.

## Data
- All 30 evaluation reports are synthetic. Real lab reports were used only as format
  references for layouts and were not copied into the repository or into any evaluation.
- No real patient data is stored in this repository.

## Verification
- Every number in the README comes from the eval script, not from an AI summary.
- Things AI suggested that I rejected or changed are listed here as they happen:
  - Name matcher: kept only as a fallback after the dictionary, with every model mapping
    marked "please verify", after measurement showed it does not beat the dictionary.
  - Critical values always show their low/high direction instead of a generic "critical".
  - Dropped the private check against real reports, to keep real data out of the project.
