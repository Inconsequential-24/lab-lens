# Templates for requirements-discovery

## Requirements spec

```markdown
# <Title>
Status: DRAFT            <!-- becomes APPROVED (<date>, by user) only after explicit approval -->

## Objective
## Problem statement
## Functional requirements
- FR-01: ...
## Non-functional requirements
- NFR-01: ... (performance, security, accessibility, cost, maintainability)
## User stories / use cases
- As a <role>, I want <x> so that <y>.
## Inputs and outputs
## Constraints
## Edge cases
## Security and privacy considerations
## Dependencies
## Assumptions
## Explicit non-goals
## Acceptance criteria
- AC-01 (FR-01): Given/When/Then ...
## Testing requirements
## Outstanding decisions
```

## Implementation plan

| Task | Objective | Reqs | Files / components (Verified · To investigate) | Depends on | Proposed implementation | Verification | Risks | Done when |
|---|---|---|---|---|---|---|---|---|
| T-01 | ... | FR-01 | `src/x.ts` (Verified) | — | ... | unit test `x.test.ts` | ... | AC-01 passes |

## Traceability / verification tracker

| Req | Acceptance | Test / check | Result (Passed · Failed · Blocked · Not executed · N/A) |
|---|---|---|---|
