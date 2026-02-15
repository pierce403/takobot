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
- Pairing is terminal-first outbound XMTP.
- After pairing, XMTP is the control plane for identity/config/tools/permissions/routines.
- Local terminal chat remains available as a cockpit.

## Core checks

- `takobot` opens the TUI.
- `takobot doctor` reports local/offline diagnostics.
- `takobot run` starts daemon mode directly.
