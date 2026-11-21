---
name: documentation-research
description: Hermione's Library procedure for researching official docs, library APIs, versions, release notes, security advisories and papers, with cited, version-aware findings. Use when a decision or implementation depends on external technical facts or on an API you have not verified.
user-invocable: false
---

# Documentation research (Hermione's Library)

## Procedure
1. **Frame the question.** What exactly must be known, and for which version?
2. **Check installed versions first.** Look at lockfiles and manifests (`package-lock.json`, `pnpm-lock.yaml`, `requirements*.txt`, `poetry.lock`, `go.mod`, `Cargo.lock` …).
3. **Library APIs:** use Context7 `resolve-library-id` and then `query-docs` with a narrow query. If the Context7 tools aren't present, say so and fall back.
4. **Current or external facts** (releases, deprecations, CVEs, standards): one targeted WebSearch, then WebFetch on the official page with a specific prompt. Context7 does not replace web search for freshness.
5. **GitHub sources:** use the `gh` CLI or a GitHub MCP if one is configured; otherwise WebFetch the official repository pages.
6. **Stop** when the question is answered with adequate evidence. Don't keep searching for completeness.

## Evidence hierarchy
1. Official product docs and API references
2. Official repositories, release notes, security advisories
3. Standards bodies and original research
4. Reputable technical publications
5. Community discussions, labelled **[community]**

## Rules
- Cite a link for every important claim and note the source date and applicable version.
- Label each claim **Verified** (seen in a source) or **Inference**.
- Report conflicts between sources rather than silently picking one.
- Never invent sources, URLs, API methods, versions, or results. If you couldn't find it, say "not found".
- Recommend; don't expand implementation scope.

## Report
```
Research question:
Findings: (bullets, each with [Verified|Inference] and a source link)
Sources: (link — publisher — date — version)
Applicable versions / dates:
Limitations:
Confidence: high | medium | low (why)
Unresolved questions:
Recommended next steps:
```
