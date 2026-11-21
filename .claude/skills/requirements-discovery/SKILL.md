---
name: requirements-discovery
description: Prof. Dumbledore's workflow - turn a vague or substantial request into a requirements spec (FR/NFR IDs) and implementation plan, ask only high-value clarification questions, and gate implementation on explicit user approval. Use before any substantial feature, multi-file change, architecture change, new dependency, or data change.
user-invocable: false
---

# Requirements discovery (Prof. Dumbledore)

Runs in the **main conversation**, because it needs back-and-forth with the user. The `dumbledore` subagent may be used only to draft the spec/plan from already-gathered context.

## When to use it
- Substantial: new feature, more than ~2 files, architecture or schema change, new dependency, data migration, security-sensitive change, or an ambiguous goal.
- Trivial (skip it, just do it and verify): one-file reversible edits like a colour, copy, typo, or config value. Don't over-plan.

## Phases
- **A. Understand:** restate the goal in one or two sentences and name the user-visible outcome.
- **B. Inspect context:** read the conversation, CLAUDE.md, and the relevant code (search first, see `token-optimization`). Record what you verified versus what you inferred.
- **C. Clarify:** ask only questions that affect architecture, cost, security, functionality, or major rework.
  - Batch them into one round of at most 4, using AskUserQuestion when available.
  - **Every multiple-choice question includes "Other — please specify".**
  - Add "Not sure — recommend an option" when the user may lack context, and put your recommended option first.
  - Never ask what's already answered or discoverable.
  - Minor reversible choices: assume, and list the assumption.
- **D. Finalize requirements:** write them with the template in [templates.md](templates.md), with stable IDs FR-01…, NFR-01….
- **E. Plan:** write the task table from templates.md and map each FR/NFR to acceptance criteria and tests. Mark file locations **Verified** (you saw them) or **To investigate**. Point out simplifications and token-saving options.
- **F. Present:** save to `<project>/docs/plans/<slug>.md` with `Status: DRAFT`, show a short summary (not the whole file), and offer the review options below.
- **G. Wait:** stop and do nothing substantial until approval.
- **H. Implement within scope:** after explicit approval, set `Status: APPROVED (<date>, by user)` and proceed. Anything outside the plan needs a new approval.
- **I. Track:** keep a verification table (requirement → test → result) up to date. Done means every acceptance criterion is verified or explicitly listed as unverified.

## Review options (offer exactly these)
1. Approve and proceed
2. Modify the requirements
3. Modify the implementation plan
4. Ask more questions
5. Reduce scope
6. Other — please specify

## Approval rules
- Only an unambiguous yes counts: "approve", "approved", "go ahead", "proceed", or option 1. "Looks interesting", "ok?", "maybe", or silence are **not** approval. Ask again instead.
- If the user asks for changes, revise the document, keep it DRAFT, and ask again.
- Approval never authorizes commits, pushes, deployments, dependency installs, destructive operations, database writes, or browser automation. Each of those needs its own explicit permission.
- If you hit a new material risk or ambiguity mid-implementation, stop that part, explain, and ask.
