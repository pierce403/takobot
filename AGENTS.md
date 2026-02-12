# AGENTS.md — Tako

Tako is a **highly autonomous, operator-imprinted agent**: it can chat broadly, but only the operator can change its configuration, capabilities, tools, or routines.

This file is the repo’s “how to work here” contract for humans and agents. Keep it short, concrete, and up to date.

## Repo Contract

Required files (must exist):

- `AGENTS.md` (this file)
- `SOUL.md` (identity + boundaries; not memory)
- `VISION.md` (1-page invariants)
- `memory/MEMORY.md` (canonical durable memory; long-lived facts only)
- `ONBOARDING.md` (first wake checklist)
- `FEATURES.md` (feature tracker + stability + test criteria)
- `index.html` (project website)

Root directories (must exist):

- `tools/` (tool implementations + manifests)
- `memory/` (committed memory tree: `MEMORY.md`, `dailies/`, `people/`, `places/`, `things/`)
- `.tako/` (runtime only; never committed)

## Safety Rules (non-negotiable)

- **No secrets in git.** Never commit keys, tokens, or `.tako/**`.
- **No encryption in the working directory.** Startup must be “secretless” (no external secrets required).
- **Keys live unencrypted on disk** under `.tako/` with OS file permissions as the protection.
- **Refuse unsafe states** (e.g., if a key file is tracked by git).
- **XMTP Operator Channel is the ONLY control plane.** No user-facing configuration via CLI flags or environment variables.

## Operator Imprint (control plane)

- Operator is the sole controller for: identity changes (`SOUL.md`), tool/sensor enablement, permission changes, routines, and configuration.
- Non-operator chats may converse and suggest tasks, but must not cause risky actions without operator approval.
- If a non-operator attempts to steer identity/config, respond with a firm “operator-only” boundary.

## Multi-instance Safety

- `tako` must avoid running twice against the same `.tako/` state (use locks).
- State that is not meant for git lives under `.tako/state/**` (ignored).

## Working Agreements

- **Commit and push** on every meaningful repo update (keep commits small and reviewable).
- Keep `index.html`, `README.md`, and `FEATURES.md` aligned with current behavior and entrypoints.
- When changing behavior, update docs + website + feature tracker together.

## Lessons Learned (append-only)

Add new notes at the top using `YYYY-MM-DD`, with a short title and a few bullets:

### YYYY-MM-DD — Title

- What happened:
- Fix:
- Prevention:

### 2026-02-12 — TUI activity visibility + auto-pair startup

- What happened: onboarding still required manual pairing code copyback and identity prompts could fire before the agent had performed live inference.
- Fix: switched pairing to outbound-assume-ready, delayed identity/routine prompts until inference is actually active, and added a visible activity panel + clipboard-friendly controls in the TUI.
- Prevention: keep first-run friction low, surface runtime actions explicitly in-UI, and avoid identity capture before the model loop is truly awake.

### 2026-02-11 — Terminal app became the primary runtime loop

- What happened: startup UX was still designed around shell prompts + daemon subcommands, which made first-run flow brittle and fragmented.
- Fix: switched default entrypoint to interactive app mode (`tako`), moved onboarding into an explicit in-app state machine, and made daemon tasks background coroutines under UI orchestration.
- Prevention: treat subcommands as dev/automation paths only; keep operator-facing flow in the persistent terminal UI.

### 2026-02-11 — Terminal-first outbound pairing

- What happened: inbound XMTP stream health during bootstrap was unreliable, making first pairing brittle.
- Fix: moved first pairing to terminal-first flow: ask operator handle, send outbound DM challenge, confirm code in terminal, then switch to XMTP-only management.
- Prevention: keep bootstrap independent of inbound stream availability; treat stream issues as runtime delivery concerns with polling fallback.

### 2026-02-10 — Memory tree moved under `memory/`

- What happened: daily logs and canonical memory were spread between root `MEMORY.md` and `daily/`.
- Fix: moved to `memory/MEMORY.md` + `memory/dailies/` with dedicated `people/`, `places/`, and `things/` note spaces.
- Prevention: keep memory strategy and directory purpose documented in `memory/README.md` and per-directory README files.

### 2026-02-10 — Keys live in `.tako/keys.json` (not committed)

- What happened: early versions wrote keys to `.tako/config.json`; the new contract uses `.tako/keys.json`.
- Fix: migrate legacy `.tako/config.json` → `.tako/keys.json` and add safety checks to refuse tracked `.tako/**`.
- Prevention: treat `.tako/keys.json` as sensitive and keep `.tako/` ignored by git.

### 2026-02-10 — Keep local XMTP DBs out of git

- What happened: local `*.db3` files were easy to accidentally leave in the repo root.
- Fix: ignore `*.db3`, `*.db3-wal`, and `*.db3-shm`.
- Prevention: treat all local XMTP DB artifacts and `.tako/keys.json` (and legacy `.tako/config.json`) as sensitive runtime state.
