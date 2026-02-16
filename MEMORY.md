---
title: "Tako Memory Frontmatter"
type: "memory-frontmatter-spec"
version: 3
updated: 2026-02-16
---

# MEMORY.md — Memory-System Frontmatter Spec

`MEMORY.md` is the root memory contract. It is not a daily note and not a task board.

## Scope

Use this file to define how memory is organized and what belongs where.

## What Belongs Under `memory/`

### `memory/dailies/YYYY-MM-DD.md`

Use for session-level chronology and observations:

- what happened today
- notable decisions made today
- runtime anomalies and short outcomes
- candidate items to promote into durable memory

### `memory/world/`

Use for accumulated research and world model artifacts:

- `memory/world/YYYY-MM-DD.md` for deterministic world-watch capture
- `memory/world/model.md` for current world model and mission hypotheses
- `memory/world/entities.md` for tracked entities/sources
- `memory/world/assumptions.md` for explicit assumptions + confidence tags

### `memory/reflections/`

Use for metacognitive reflections:

- lessons learned from behavior
- patterns in mistakes and improvements
- strategy adjustments that are not immediate tasks

### `memory/contradictions/contradictions.md`

Use for contradiction tracking:

- conflicting claims or observations
- status: open/resolved/parked
- evidence and resolution notes

## What Does Not Belong In Memory

Execution artifacts live outside `memory/`:

- `tasks/` for actionable next actions
- `projects/`, `areas/`, `resources/`, `archives/` for PARA/GTD execution structure
- transient runtime state under `.tako/`

## Safety Rules

- Never store secrets, tokens, or private keys in memory files.
- Keep memory markdown deterministic and diff-friendly.
- Promote only durable facts/policies to this root file when needed.
