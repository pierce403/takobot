---
summary: "Bootstrap and first-run flow for Takobot"
read_when:
  - You are creating a new Takobot workspace
  - You want to verify first-run behavior
title: "Quickstart"
---

# Quickstart

## Bootstrap

```bash
mkdir takobot-workspace
cd takobot-workspace
curl -fsSL https://tako.bot/setup.sh | bash
```

What bootstrap does:

- creates `.venv/`
- installs/updates `takobot` from PyPI
- installs a local pi runtime under `.tako/pi/node` (bootstraps workspace-local nvm/node when host Node/npm is missing or Node is `<20`)
- materializes workspace templates without overwriting edits
- initializes git on `main`
- launches TUI when a TTY is available, otherwise starts daemon mode

## First run

- TUI starts in onboarding state.
- Hatchling onboarding order is stage-aware: `name -> purpose -> XMTP handle?`.
- On onboarding completion, Tako transitions into `child` stage behavior (world learning).
- In `child` stage chat, Tako asks lightweight context questions first (who/where/what you do), records notes in `memory/people/operator.md`, and can add your favorite websites to `[world_watch].sites`.
- In `child` stage, world learning includes random curiosity crawls across Reddit, Hacker News, and Wikipedia with mission-linked questions.
- If runtime stays idle, boredom cues lower emotional indicators and trigger autonomous exploration to seek novelty.
- Inference uses focus-aware memory recall: emotional focus level controls `ragrep` retrieval breadth from `memory/` (narrow when focused, broad when diffuse).
- Pairing is terminal-first outbound XMTP.
- After pairing, XMTP provides remote control for identity/config/tools/permissions/routines.
- Pairing/runtime now verifies XMTP profile metadata against identity when possible, repairs mismatches when profile update APIs are available, and publishes fallback profile metadata messages (`tako:profile:{...}`) to self/known DMs for compatible clients. It also creates local deterministic avatar/sync caches (`.tako/state/xmtp-avatar.svg`, `.tako/state/xmtp-profile.json`, `.tako/state/xmtp-profile-broadcast.json`).
- Recurring jobs can be scheduled from natural language (for example `every day at 3pm run doctor`) and are stored in `.tako/state/cron/jobs.json`.
- Local terminal remains full operator control (including config changes), and chat stays available as a cockpit.
- First-run templates include `resources/model-guide.md` for model family and thinking-level tuning.

## Core checks

- `takobot` opens the TUI.
- `tako.sh` is installed with the package and also materialized into fresh workspaces as a local launcher; deployed mode dispatches to installed `takobot`.
- Memory notes are written under `memory/` (world-watch notebook under `memory/world/`).
- Pi chat turn summaries are visible in logs (`.tako/logs/runtime.log` and `.tako/logs/app.log`).
- Inference command failures are logged to `.tako/logs/error.log` with invoked command + stderr/stdout tails.
- `takobot doctor` reports local/offline diagnostics.
- `takobot run` starts daemon mode directly.
- `jobs` / `jobs list` shows scheduled jobs; `jobs add <natural schedule>` creates one.
