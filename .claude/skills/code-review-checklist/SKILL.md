---
name: code-review-checklist
description: Harry's independent code review and security audit checklist - correctness, edge cases, security, secrets, dependency changes, scope creep, missing tests, commit readiness - with redacted, evidence-based findings. Use when reviewing a diff, auditing security, or checking Git commit readiness.
user-invocable: false
---

# Code review checklist (Harry)

## Scope
1. Get the actual change: `git status --short`, `git diff --stat`, `git diff` (and `git diff --cached`), or the target the user names.
2. Read the surrounding code for every non-trivial hunk, by range.
3. If the git root is `$HOME` or the diff includes unrelated personal files, stop and report it. Don't review the home directory.

## Checklist
- Logic and correctness; edge cases (empty, null, large, concurrent, unicode, timezones)
- Error handling and input validation
- AuthN/AuthZ checks on every new entry point
- Injection: SQL, shell, path traversal, XSS, SSRF, template, deserialization
- Sensitive data in logs or error messages
- Hardcoded secrets; `.env`, key, or credential files staged or untracked-but-unignored
- Dependency changes: new packages, version bumps, lockfile drift, install scripts
- Performance regressions (N+1, unbounded loops or queries, sync I/O on hot paths)
- Scope creep beyond the approved plan
- Missing or weakened regression tests
- Commit readiness: unrelated files, debug code, TODOs, generated artefacts

## Deterministic scanners (use what is installed, never install without approval)
- `command -v gitleaks && gitleaks detect --no-banner --redact --source .` (or `gitleaks protect --staged --redact` for staged changes)
- `command -v semgrep && semgrep scan --config auto --error --quiet` (needs network for rules; say so if blocked)
- Language analyzers already present in the repo: eslint, ruff, bandit, `npm audit`, `pip-audit`
- **Fallback when no scanner is installed:** a heuristic grep, labelled "heuristic, not a scanner":
  `git diff -U0 | grep -nEi '(api[_-]?key|secret|token|passw(or)?d|private[_-]?key|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|sk-[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY)'`
  Also run `git ls-files --others --exclude-standard | grep -E '(^|/)\.env|\.pem$|\.key$'`.

## Reporting
For each finding:
```
[SEVERITY: Critical|High|Medium|Low|Info] [Confirmed|Potential]
File: path:line
Evidence: (describe; quote code only if it contains no secret)
Impact:
Recommended fix:
```
- **Never reproduce a secret.** Show only the type and location, e.g. `AWS access key at config.ts:12 (value redacted: AKIA****)`.
- Separate confirmed problems from potential risks.
- List the scanners run, with exit codes, and those not run with the reason.
- Never claim the code is "secure" or "vulnerability-free". Say what was checked.
- Read-only: don't modify code unless explicitly assigned remediation. Never commit, push, or publish.
- End with a **Commit readiness** verdict (Ready / Ready with nits / Not ready) and the blockers.
