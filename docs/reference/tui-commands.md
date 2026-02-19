---
summary: "Reference of local TUI and XMTP command surfaces"
read_when:
  - You need an operator command quick-reference
title: "TUI + Runtime Commands"
---

# TUI + Runtime Commands

## Local TUI commands

Common commands:

- `help`, `status`, `stats`, `health`, `inference`, `models`, `doctor`
- `stage`, `stage show`, `stage set <hatchling|child|teen|adult>`
- `pair`, `setup`, `reimprint`
- `update`, `upgrade`, `update check`, `update auto status|on|off`
- `dose`, `dose calm`, `dose explore`, `dose <d|o|s|e|dopamine|oxytocin|serotonin|endorphins> <0..1>`
- `explore`, `explore <topic>` (manual exploration tick; auto-selects a mission-aligned topic when omitted, bypasses normal poll windows, avoids immediate auto-topic repeats, and for explicit topics writes structured research notes plus a synthesized mission-linked insight from evidence)
- `jobs`, `jobs list`, `jobs add <natural schedule>`, `jobs remove <id>`, `jobs run <id>`
- `web <url>`, `run <command>`
- `task`, `tasks`, `done`, `morning`, `outcomes`, `compress`, `weekly`, `promote`
- `install`, `review pending`, `enable`, `draft`, `extensions`
- `safe on`, `safe off`
- `inference login` starts an assisted pi login workflow. When prompts appear, answer with `inference login answer <text>` or cancel with `inference login cancel`.
- `models` reports the effective Type1/Type2 pi model plan and the last streamed model observed in TUI. Defaults are tuned for split cognition: Type1 fast (`minimal`), Type2 deep (`xhigh`).
- Natural-language scheduling also works in plain chat text (for example: `every day at 3pm explore ai news`, `at 09:30 every weekday run doctor`).
- Type `/` in the input box to open the slash-command dropdown under the input field.
- Press `Tab` in the input box to autocomplete command names (and cycle candidates).
- Asking purpose info questions (for example, `what is your purpose?`) returns the current purpose text; purpose updates still require explicit replacement wording.

Clipboard helpers:

- `Ctrl+Shift+C` copy transcript
- `Ctrl+Shift+L` copy last line
- `Ctrl+V` / `Shift+Insert` paste
- Right-click on selected transcript/stream text copies the current selection via Takobot clipboard helpers.

Input history:

- `Up` / `Down` cycles previously submitted local messages

Thinking visibility:

- Bubble stream shows current request focus and elapsed time while the model is thinking/responding.
- For pi inference, bubble stream now surfaces live thinking/tool-progress/status events from pi JSON mode while a turn is running.
- During longer inference turns, bubble stream emits periodic debug wait updates and local chat has a bounded total timeout budget.

## XMTP operator command surface

Primary commands:

- `help`, `status`, `doctor`
- `config`
- `jobs` (`jobs list|add <natural schedule>|remove <id>|run <id>`)
- `update`
- `web <url>`
- `run <command>`
- `reimprint`

Plain-text non-command messages are treated as chat, except operator schedule requests like `every day at 3pm ...`, which are interpreted as job creation.
`jobs run` over XMTP requires the terminal app runtime queue (daemon-only mode cannot execute immediate local-run triggers).
