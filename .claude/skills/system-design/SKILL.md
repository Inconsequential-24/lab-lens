---
name: system-design
description: Architecture evaluation (Prof. McGonagall) and HLD/LLD authoring (Ron) - principles, database selection, trade-offs, failure modes, scaling, and report templates with Mermaid diagrams. Use for architecture decisions, technology or database choice, or producing design documents.
user-invocable: false
---

# System design

## Principles
- KISS, DRY, YAGNI.
- Separation of concerns, loose coupling, high cohesion.
- Security by design, maintainability, and observability where it pays off.
- **Scaling:** consider horizontal scaling early, but add distributed-system complexity (queues, sharding, microservices, caches) only when a stated requirement justifies it. Name the requirement.
- Prefer incremental change to rewrites, and the existing stack to new technology.

## Procedure
1. Read the approved requirements, if any. With none, list the assumed ones and flag them.
2. Inspect the existing architecture: entry points, modules, data stores, integrations. Search first and read ranges.
3. Map components, boundaries and data flow.
4. Choose and justify: compare at least 2 realistic alternatives on requirements fit, complexity, cost and operations.
5. **Database selection:** decide from the data model, query patterns, consistency and transaction needs, expected scale, and operational cost.
6. Cover failure modes, reliability, performance, security, and observability.
7. Identify the files and components likely to change, and the decisions that need user approval.
8. Never implement code during analysis.

## Honesty rules
- Mark everything **Existing (verified at path:line)** or **Proposed**. Never invent existing classes, files, or APIs.
- Keep documents proportional. A small feature gets one page, not a full HLD.
- Use Mermaid (`flowchart`, `sequenceDiagram`, `erDiagram`) only when it clarifies something.

Templates for the architecture report, HLD and LLD are in [templates.md](templates.md). Include only the sections that matter for the task.
