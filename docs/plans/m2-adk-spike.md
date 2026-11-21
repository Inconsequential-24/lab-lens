# Milestone 2: ADK 2.0 spike and API key setup

Status: APPROVED (2026-11-21, by user; google-adk install approved)

## Goal
Confirm the ADK 2.0 Workflow API works with a Gemini API key on this machine, using a
two-node workflow, before any real pipeline code is written (PLAN.md section 12, milestone 2).

## Requirements
- FR-01: ADK 2.0 `Workflow` with a function node (parse a hard-coded test row), a Gemini
  `Agent` node (`gemini-3.1-flash-lite`) returning a Pydantic type, and a router node; runs
  in `adk web` (PLAN.md milestone 2).
- FR-06: Confirm each open item in PLAN.md section 4.1 (function-node signature, typed
  output, fan-out syntax, shared state, `Runner` inside FastAPI, node retry config) and
  update section 4.1 with the findings.
- FR-02: The API key is read from `.env` (`GOOGLE_API_KEY`), never hard-coded or logged.
- FR-03: Commit `.env.example` with variable names only (no values).
- FR-04: Pin the exact working `google-adk` version in `requirements.txt`.
- FR-05: Record the confirmed import paths and class names in PLAN.md section 12
  (the "unverified assumptions" bullet becomes verified, or is corrected).
- NFR-01: Spike costs well under ₹5; token counts printed.
- NFR-02: No report data in the spike; one hard-coded synthetic row only.

## Tasks
| # | Task | Files | Location |
|---|---|---|---|
| 1 | Look up current ADK 2.0 Workflow docs and the latest release (Hermione's Library) | none | To investigate |
| 2 | Create venv, install `google-adk` (needs your OK) | `requirements.txt` | New |
| 3 | Add `.env.example` with `GOOGLE_API_KEY=` and `GOOGLE_GENAI_USE_VERTEXAI=FALSE` | `.env.example` | New (`.gitignore` already allows it, verified) |
| 4 | Write the spike | `spikes/adk_two_node.py` | New |
| 5 | Run it once with your paid-tier key | none | Needs your key in `.env` |
| 6 | Update PLAN.md section 12 with what was confirmed | `PLAN.md` | Verified |

## Acceptance
- Running `python spikes/adk_two_node.py` prints the parsed row, one sentence from the model,
  and input/output/thinking token counts.
- `git grep -i "AIza"` finds nothing (no key committed).

## Assumptions
- The env var names follow ADK's long-standing convention (`GOOGLE_API_KEY`); task 1 confirms
  this for 2.0.
- The paid-tier Gemini API key is used (PLAN.md sections 8 and 10).
