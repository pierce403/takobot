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

- Primary contract files live at repo root (`AGENTS.md`, `SOUL.md`, `MEMORY.md`, `SKILLS.md`, `TOOLS.md`, `FEATURES.md`, `tako.toml`, `index.html`).
- Productivity + memory directories are committed (`tasks/`, `projects/`, `areas/`, `resources/`, `archives/`, `memory/**`).
- `SOUL.md`, `MEMORY.md`, `SKILLS.md`, and `TOOLS.md` are loaded as bounded frontmatter context each chat cycle.
- `code/` is git-ignored and used for cloned repos/sandbox code work.

## Runtime

All mutable runtime state is under `.tako/`:

- `keys.json`, `operator.json`
- `logs/` (`runtime.log`, `app.log`; includes pi chat turn summaries)
- `state/` (events, DOSE, open loops, inference metadata, conversation sessions, boredom/briefing cadence state)
- `state/rss_seen.json`, `state/curiosity_seen.json`, `state/operator_profile.json`, and `state/briefing_state.json` (world-watch dedupe + child-stage operator modeling + briefing cadence state)
- `tmp/` (workspace-local temp files)
- `xmtp-db/`
- `pi/` (workspace-scoped pi runtime/auth/session state)

World-watch notes are committed under `memory/world/` so research accumulation stays visible in git history. In `child` stage, world-watch also samples Reddit/Hacker News/Wikipedia and records mission-linked questions.
Child-stage operator notes are committed under `memory/people/operator.md`, and captured website preferences are persisted in `tako.toml` (`[world_watch].sites`).
Life-stage policy is persisted in `tako.toml` (`[life].stage`) and shapes exploration cadence, Type2 budgets, and DOSE baseline multipliers.
When runtime stays idle, boredom signals are emitted into the event stream, DOSE drifts downward, and Takobot triggers autonomous exploration to re-seek novelty.

This keeps runtime writes inside the workspace while preserving git cleanliness.
