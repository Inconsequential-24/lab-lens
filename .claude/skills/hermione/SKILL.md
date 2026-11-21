---
name: hermione
description: Implement a change with Hermione - trivial edits directly; substantial tasks only from an APPROVED plan, followed by Harry review, Snape verification and Hagrid docs as needed.
argument-hint: <task or docs/plans/<slug>.md>
disable-model-invocation: true
---

# /hermione — implement

Task: $ARGUMENTS

## 1. Approval gate (do not skip)
- **Trivial and reversible** (one file, cosmetic or config value): go to step 2.
- **Substantial**: a plan file must exist with `Status: APPROVED`, either named in the arguments or found in `docs/plans/`.
  - If there's no plan, or it's DRAFT, **don't implement**. Say so and run the `/dumbledore` workflow for this task instead.
  - The user saying "just implement it" doesn't replace plan approval for a substantial task. Offer a reduced-scope plan instead.
- Approval covers only the plan's scope. Commits, pushes, deploys, installs, destructive operations, DB writes and browser automation each still need separate explicit permission.

## 2. Implement
- Trivial: do it here directly. Find the file, make the minimal edit, run one quick check.
- Substantial: delegate to the `hermione` subagent with the plan path and task IDs, or do it inline if the change is small enough. Use `hermiones-library` first only if an API or version is unverified.

## 3. Close the loop (proportional to risk)
- `harry` reviews the diff, for substantial changes.
- `snape` runs targeted then broader checks.
- `hagrid` updates docs, only if feature ownership, architecture, config or data flow changed.
- Run Harry and Snape in parallel when both are needed.

## 4. Report
Report files changed, requirements satisfied, check results (Passed, Failed, Blocked or Not executed) and outstanding items. Update the plan's verification tracker.
