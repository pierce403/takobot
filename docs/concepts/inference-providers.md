---
summary: "Inference provider detection, fallback, and pi runtime integration"
read_when:
  - You are debugging provider selection
  - You need to understand Takobot’s pi-based inference path
title: "Inference Providers"
---

# Inference Providers

Takobot discovers provider runtimes at startup and keeps ordered fallback.

## Provider order

Current priority:

1. `pi`
2. `codex`
3. `claude`
4. `gemini`

The first ready provider is selected; failures fall through to the next ready provider.

## pi runtime path (OpenClaw-style)

Takobot follows OpenClaw’s pi stack direction by using `@mariozechner/pi-*` runtime packages.

- Bootstrap installs local packages into `.tako/pi/node` (best-effort):
  - `@mariozechner/pi-ai`
  - `@mariozechner/pi-coding-agent`
- Inference uses local `pi` binary when present (`.tako/pi/node/node_modules/.bin/pi`).
- Runtime sets `PI_CODING_AGENT_DIR=.tako/pi/agent` so pi auth/session writes stay in workspace.

## pi invocation mode

Takobot runs pi in non-interactive inference mode:

- `--print`
- `--mode text`
- `--no-session`
- `--no-tools`
- `--no-extensions`
- `--no-skills`

This keeps responses deterministic and prevents unintended tool-side effects.

## Auth sources

Readiness checks include:

- common provider API-key env vars
- workspace-local `.tako/pi/agent/auth.json`
- fallback auth files in `~/.pi/**` (copied into workspace on first use when possible)

## Diagnostics

- `inference` command in TUI reports selected provider and readiness.
- `doctor` includes offline inference probes and recent inference error scan.
