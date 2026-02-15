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
- `pair`, `setup`, `reimprint`
- `update`, `upgrade`, `update check`, `update auto status|on|off`
- `dose`, `dose calm`, `dose explore`, `dose <d|o|s|e|dopamine|oxytocin|serotonin|endorphins> <0..1>`
- `web <url>`, `run <command>`
- `task`, `tasks`, `done`, `morning`, `outcomes`, `compress`, `weekly`, `promote`
- `install`, `review pending`, `enable`, `draft`, `extensions`
- `safe on`, `safe off`
- Type `/` in the input box to open the slash-command dropdown under the input field.
- Press `Tab` in the input box to autocomplete command names (and cycle candidates).

Clipboard helpers:

- `Ctrl+Shift+C` copy transcript
- `Ctrl+Shift+L` copy last line
- `Ctrl+V` / `Shift+Insert` paste
- Native terminal right-click copy is supported for selected transcript text.

Input history:

- `Up` / `Down` cycles previously submitted local messages

Thinking visibility:

- Bubble stream shows current request focus and elapsed time while the model is thinking/responding.

## XMTP operator command surface

Primary commands:

- `help`, `status`, `doctor`
- `config`
- `update`
- `web <url>`
- `run <command>`
- `reimprint`

Plain-text non-command messages are treated as chat.
