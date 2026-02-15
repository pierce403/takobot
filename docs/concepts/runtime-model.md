---
summary: "Engine/workspace/runtime model used by Takobot"
read_when:
  - You are changing startup or filesystem behavior
  - You need to debug where data should live
title: "Runtime Model"
---

# Runtime Model

Takobot uses a three-part model:

1. **Engine** (installed Python package)
2. **Workspace** (git-tracked docs/tasks/config)
3. **Runtime** (`.tako/`, never committed)

## Engine

- Installed via `pip install takobot`.
- Provides templates (`takobot/templates/**`) and runtime code.

## Workspace

- Primary contract files live at repo root (`AGENTS.md`, `SOUL.md`, `MEMORY.md`, `FEATURES.md`, `tako.toml`, `index.html`).
- Productivity + memory directories are committed (`tasks/`, `projects/`, `areas/`, `resources/`, `archives/`, `memory/**`).
- `code/` is git-ignored and used for cloned repos/sandbox code work.

## Runtime

All mutable runtime state is under `.tako/`:

- `keys.json`, `operator.json`
- `logs/` (`runtime.log`, `app.log`)
- `state/` (events, DOSE, open loops, inference metadata, conversation sessions)
- `tmp/` (workspace-local temp files)
- `xmtp-db/`
- `pi/` (workspace-scoped pi runtime/auth/session state)

This keeps runtime writes inside the workspace while preserving git cleanliness.
