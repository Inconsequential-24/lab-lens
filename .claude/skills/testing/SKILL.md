---
name: testing
description: Snape's risk-based verification procedure - discover the repo's real test, lint, typecheck and build commands, run targeted checks first, report honest result states, and follow the browser-automation permission protocol. Use when verifying a change, running tests, or deciding what to check before shipping.
user-invocable: false
---

# Testing and verification (Snape)

## 1. Discover, don't assume
Look for the repo's real commands in `package.json` scripts, `Makefile`, `pyproject.toml`/`tox.ini`/`noxfile.py`, `Cargo.toml`, `go.mod`, CI files (`.github/workflows/*`), and the README or CLAUDE.md. Use those commands as written.

## 2. Risk-based order
1. Targeted: tests for the files or modules changed.
2. Static checks: lint and typecheck on the changed files or package.
3. Broaden by risk: the full unit suite, integration tests, build.
4. Security when relevant: the secret scan (see `code-review-checklist`), dependency audit (`npm audit`, `pip-audit`) if available.
5. E2E or browser tests only if the change is UI or flow-level **and** cheaper checks can't verify it (see section 4).

Route noisy runs through `log-digest`. Check the real exit code of every command.

## 3. Result states (use exactly these)
**Passed** · **Failed** · **Blocked** (couldn't run, give the reason) · **Not executed** · **Not applicable**
- Never report a test as passed unless you ran it and saw it pass.
- Never weaken, skip, or edit tests to hide an implementation defect. Report the defect.

## 4. Browser automation protocol (mandatory)
Playwright MCP, browser-control MCPs and `npx playwright` are permission-gated by settings and hooks. Before any use:
1. Explain why browser access is necessary.
2. Explain why unit, integration or static checks are insufficient.
3. List the exact intended actions (URLs, clicks, forms; no real credentials).
4. Ask the user for explicit permission and **wait**.
Never use a browser just because it's available. If permission is denied, mark those checks Blocked.

## 5. Report
```
Checks executed: (command — exit code — state)
Results:
Requirements verified: (FR/AC IDs)
Requirements not verified: (and why)
Remaining risks:
Recommended next steps:
```
