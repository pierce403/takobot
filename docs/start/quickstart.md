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
- installs a local pi runtime under `.tako/pi/node` when `npm` is available
- materializes workspace templates without overwriting edits
- initializes git on `main`
- launches TUI when a TTY is available, otherwise starts daemon mode

## First run

- TUI starts in onboarding state.
- Hatchling onboarding order is stage-aware: `name -> purpose -> XMTP handle?`.
- On onboarding completion, Tako transitions into `child` stage behavior (world learning).
- In `child` stage, world learning includes random curiosity crawls across Reddit, Hacker News, and Wikipedia with mission-linked questions.
- Pairing is terminal-first outbound XMTP.
- After pairing, XMTP provides remote control for identity/config/tools/permissions/routines.
- Local terminal remains full operator control (including config changes), and chat stays available as a cockpit.

## Core checks

- `takobot` opens the TUI.
- `tako.sh` is installed with the package as a shell wrapper; in deployed environments it dispatches to the installed `takobot`.
- Memory notes are written under `memory/` (world-watch notebook under `memory/world/`).
- `takobot doctor` reports local/offline diagnostics.
- `takobot run` starts daemon mode directly.
