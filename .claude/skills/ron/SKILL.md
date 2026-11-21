---
name: ron
description: Design workflow - McGonagall's architecture evaluation and/or Ron's HLD/LLD documents for a feature, system or approved plan.
argument-hint: <topic or docs/plans/<slug>.md> [hld|lld|arch]
disable-model-invocation: true
---

# /ron — architecture and design

Target: $ARGUMENTS

1. If a `docs/plans/*.md` is named or obviously relevant, use its requirements. Otherwise state the assumed requirements.
2. Choose the minimum needed:
   - Technology, database or architecture decisions → delegate to the `mcgonagall` subagent (architecture report).
   - Design documents → delegate to the `ron` subagent (HLD, LLD or both, as requested; default HLD plus a short LLD).
   - Use both only when there are real decisions **and** a document is wanted. Run McGonagall first and pass her decisions to Ron.
   - If the design depends on unverified external APIs or versions, ask `hermiones-library` first.
3. Summarize the result in under 15 lines: key decisions, open decisions needing the user's approval, doc path. Don't paste the whole report unless asked.
4. Don't implement anything.
