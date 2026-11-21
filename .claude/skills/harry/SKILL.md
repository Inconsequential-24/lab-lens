---
name: harry
description: Independent code review and security audit of the current diff (or a named path/branch) by Harry, with redacted findings and a commit-readiness verdict.
argument-hint: [path | branch | "staged"]
disable-model-invocation: true
---

# /harry — review

Target: $ARGUMENTS (default: the working-tree and staged diff of the current repo)

1. Run `git rev-parse --show-toplevel`. If it equals `$HOME`, stop. Tell the user the repo root is their home directory and they should run `git init` in the project folder.
2. Delegate to the `harry` subagent with the target and, if one exists, the approved plan path (for checking scope creep).
3. Relay the findings, sorted by severity, with secrets redacted. Then the scanners run, then the commit-readiness verdict.
4. Don't modify code. If the user wants fixes, they can run `/hermione` with the findings.
