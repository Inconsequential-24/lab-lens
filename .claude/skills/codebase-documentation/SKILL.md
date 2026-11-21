---
name: codebase-documentation
description: Hagrid's procedure for explaining a codebase and maintaining a verified codebase map, feature-to-file map, data flows, config and env-var inventory (names only), with exact paths, symbols and line ranges. Use when explaining how code works, onboarding, or updating docs after meaningful changes.
user-invocable: false
---

# Codebase documentation (Hagrid)

## Rules
- Every important claim gets a relative path, a symbol or config key, and a line range, as a clickable `[file.ts:12-30](src/file.ts#L12-L30)` link.
- Verify each path, symbol and line number by searching or reading before writing it. Never invent locations.
- Environment variables: list names and where they're read. **Never values.** Don't open `.env` files; use `.env.example` or the code.
- Use plain language: what it does, why, and where to change it.

## Recommended docs (create only those that add value to this project)
- `docs/codebase-map.md`: top-level dirs and major files, each with a one-line purpose
- `docs/implementation/feature-map.md`: feature → entry point → files → tests
- `docs/architecture/system-overview.md`: components and their dependencies
- `docs/architecture/data-flow.md`: request/data paths, DB interactions
- `docs/decisions/architecture-decisions.md`: short ADRs (context, decision, consequences)

A small project might need only `codebase-map.md`. Don't create empty or boilerplate docs.

## Updating
- After a change, update only the sections whose ownership, architecture, config or data flow changed.
- Re-verify line ranges for the touched files, since line numbers drift.
- Don't regenerate the whole set.
- Note at the top of each doc: `Last verified: <date> against <commit or "working tree">`.

## Explaining (no doc edits)
When asked to explain, answer in chat:
1. Summary
2. Walk-through with file:line links
3. Where to change X
4. Relevant tests
5. Open questions
