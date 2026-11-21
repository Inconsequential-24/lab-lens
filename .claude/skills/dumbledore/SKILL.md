---
name: dumbledore
description: Plan a substantial task with Prof. Dumbledore - clarify, write requirements (FR/NFR IDs) and an implementation plan, then wait for explicit approval.
argument-hint: <what you want built or changed>
disable-model-invocation: true
---

# /dumbledore — requirements and plan

Request: $ARGUMENTS

Run the `requirements-discovery` workflow (phases A–I) **here in the main conversation**:
1. Inspect the context first (search, then read ranges). Use `scout` if the search is broad.
2. Ask one batch of high-value questions with AskUserQuestion. Every multiple-choice question includes "Other — please specify", plus "Not sure — recommend an option" where useful.
3. Write the spec and plan to `docs/plans/<slug>.md` in the project root, using the templates. Set `Status: DRAFT`. The `dumbledore` subagent may draft this if the context is large.
4. Present a short summary plus the 6 review options, then **stop and wait**.
5. Only on an explicit approval, set `Status: APPROVED (<date>, by user)`. Then tell the user to run `/hermione docs/plans/<slug>.md`, or proceed if they said to implement.

If the request is trivial and reversible, say so and suggest just doing it instead of planning.
