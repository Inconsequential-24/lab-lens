---
name: ship
description: Pre-ship readiness check - Snape verification, Harry review, secret scan and diff inspection, ending in a Git readiness report. Never commits, pushes or deploys.
argument-hint: [optional scope or plan path]
disable-model-invocation: true
---

# /ship — readiness report (read-only)

Scope: $ARGUMENTS

1. **Repo sanity.** `git rev-parse --show-toplevel`: if it's `$HOME`, report **Not ready** (repo root is home dir) and stop. Then `git status --short`, `git branch --show-current`, `git diff --stat`, `git diff --cached --stat`.
2. **Hygiene.** Look for unrelated files, `.env`/key/credential files that are untracked or staged, large binaries, debug leftovers, and a missing `.gitignore` for those files.
3. **Run in parallel:**
   - `snape`: risk-based checks.
   - `harry`: diff review, including the secret scan (gitleaks/semgrep if installed, else the labelled grep heuristic).
4. If a plan exists, check each FR/AC against the verification results.
5. **Report:**
```
Verdict: Ready | Ready with nits | Not ready
Blockers:
Checks: (command — exit code — Passed/Failed/Blocked/Not executed)
Review findings: (severity counts + top items, secrets redacted)
Requirements verified / not verified:
Suggested commit message: (draft only)
```
6. **Never** `git add`, commit, push, tag, open a PR or deploy. If the user then explicitly asks to commit or push, do that as a separate step (permission prompts apply).
