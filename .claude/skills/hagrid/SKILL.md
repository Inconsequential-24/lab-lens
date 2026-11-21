---
name: hagrid
description: Explain how part of the codebase works with verified file:line links, or create/update the codebase map and related docs (Hagrid).
argument-hint: <question or area> | map | update
disable-model-invocation: true
---

# /hagrid — explain / map

Request: $ARGUMENTS

- **Question or area**: explain in chat using the `codebase-documentation` "Explaining" format. Use the `hagrid` subagent only if the area spans many files, and keep its summary. Don't edit any files.
- **`map`**: delegate to the `hagrid` subagent to create or refresh `docs/codebase-map.md`, plus only the other docs that add value.
- **`update`**: delegate to `hagrid` to update only the doc sections affected by the current diff (`git diff --stat`).

Every claim needs a verified relative path and line range. Give environment variable names, never values.
