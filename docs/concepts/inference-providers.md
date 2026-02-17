---
summary: "Inference provider detection, fallback, and pi runtime integration"
read_when:
  - You are debugging provider selection
  - You need to understand Takobot’s pi-based inference path
title: "Inference Providers"
---

# Inference Providers

Takobot discovers runtime/auth status for multiple providers, but executes inference through pi runtime only.

## Provider order

Execution priority:

1. `pi` (required for inference calls)

Other providers (`ollama`, `codex`, `claude`, `gemini`) are discovery/auth diagnostics only.

## pi runtime path (OpenClaw-style)

Takobot follows OpenClaw’s pi stack direction by using `@mariozechner/pi-*` runtime packages.

- Bootstrap installs local packages into `.tako/pi/node` (best-effort):
  - `@mariozechner/pi-ai`
  - `@mariozechner/pi-coding-agent`
- If host Node/npm are missing, bootstrap installs workspace-local `nvm` + Node under `.tako/nvm` first.
- npm cache is pinned to `.tako/npm-cache` so package-install artifacts stay in workspace.
- Inference uses local `pi` binary when present (`.tako/pi/node/node_modules/.bin/pi`).
- Inference prepends workspace-local Node bin from `.tako/nvm/versions/node/*/bin` to `PATH` for pi runs.
- Runtime sets `PI_CODING_AGENT_DIR=.tako/pi/agent` so pi auth/session writes stay in workspace.

## pi invocation mode

Takobot runs pi in non-interactive inference mode:

- `--print`
- `--mode text`
- `--no-session`
- thinking level is set per context when supported by the installed pi CLI:
  - Type1 calls default to `minimal` thinking
  - Type2 calls default to `xhigh` thinking

Tooling remains available in pi runtime; Takobot does not pass `--no-tools/--no-skills/--no-extensions`.

Before invoking pi, Takobot now applies a prompt safety guard:

- wraps oversized single lines to avoid downstream splitter chunk-limit failures
- trims over-budget prompts from the middle (preserving beginning + latest tail context)

## Auth sources

Readiness checks include:

- common provider API-key env vars
- runtime-local API keys from `.tako/state/inference-settings.json` (set via `inference key set ...`)
- workspace-local `.tako/pi/agent/auth.json`
- fallback auth files in `~/.pi/**` (copied into workspace on first use when possible)
- local Codex OAuth session tokens from `~/.codex/auth.json` (auto-synced into `.tako/pi/agent/auth.json` as `openai-codex` when available)
- assisted login workflow (`inference login`) that starts pi login and forwards interactive prompts back to operator input (`inference login answer <text>`)

For `pi`, Takobot also enumerates provider-specific OAuth entries from pi `auth.json` and surfaces them through `inference auth`.

## Ollama integration

- `ollama` is treated as a first-class local inference provider.
- Takobot resolves model in this order: `inference-settings.ollama_model` → `OLLAMA_MODEL` → first model from `ollama list`.
- Optional host override can be stored via `inference ollama host <url>` (sets `OLLAMA_HOST` at runtime).

## Diagnostics

- `inference` command in TUI reports selected provider and readiness.
- `inference auth` reports persisted API keys (masked) plus detected pi OAuth providers.
- `doctor` auto-repairs workspace-local pi runtime/auth first, then runs offline probes and recent inference error scan.
- Command-level inference failures (including invoked command and stderr/stdout tails) are written to `.tako/logs/error.log`.
- Unexpected provider exceptions are also appended to `.tako/logs/error.log` with traceback context, so diagnostics still exist even when failures occur before subprocess error handling.
