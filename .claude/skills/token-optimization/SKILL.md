---
name: token-optimization
description: Detailed procedures for keeping context small and work efficient - targeted search and reads, selective delegation, minimal edits, test ordering, concise reporting. Use when planning any multi-step task, exploring a codebase, delegating to subagents, or writing a final report.
user-invocable: false
---

# Token optimization

The always-on rules live in `~/.claude/CLAUDE.md`. This skill is the detailed procedure. Never trade correctness, security, or an explicit requirement for fewer tokens.

## 1. Finding code
1. Grep/Glob for the symbol, route, config key, or error string first.
2. Read only the matching line ranges (offset/limit). Whole-file reads only for files under ~300 lines you will edit.
3. If the answer needs more than ~5 files of reading, delegate to `scout` and keep only its pointers.
4. Do not re-read a file already in context unless it changed since.
5. Check installed versions (lockfile, `package.json`, `pyproject.toml`) before looking anything up.

## 2. External documentation
1. Library APIs: Context7 (`resolve-library-id` → `query-docs`) with a narrow query and the installed version.
2. Not covered or needs freshness (release notes, advisories): one targeted web search, then fetch only the relevant official page with a specific prompt.
3. Never paste whole doc pages into context; extract the few lines that matter plus the link.
4. Don't repeat a search whose answer is already in the conversation.

## 3. Questions
- Ask only what changes architecture, cost, security, behaviour, or causes rework. Discoverable facts: look them up instead.
- Batch related questions in one prompt (max 4). Never re-ask something already answered.
- Minor reversible choices: pick a sensible default and state it.

## 4. Delegation
- Delegate only for context isolation (large searches, noisy logs, independent review) or genuinely specialised reasoning.
- One agent per concern; never two agents on the same question. No nested delegation.
- Give the agent the exact files/IDs it needs so it doesn't rediscover them.
- Ask for a concise structured return; summarize it in a few lines, don't paste transcripts.
- Run independent agents in parallel only when both are actually needed.

## 5. Editing
- Smallest coherent change; no drive-by refactors or reformatting.
- Prefer existing dependencies and helpers over new ones.
- Use targeted Edit replacements instead of rewriting files.

## 6. Verification
- Targeted first: the test file / package touched, then broaden by risk (full suite, build, typecheck).
- Route noisy commands through `log-digest`.
- Report only results you actually observed; unexecuted checks are "Not executed".

## 7. Reporting
- Lead with outcome, then evidence (file:line, command + exit code), then open items.
- Don't restate unchanged context or repeat earlier messages.
- No full file dumps unless asked.
