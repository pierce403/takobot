# AGENTS.md — Tako Workspace Contract

Tako is a **highly autonomous, operator-imprinted agent**. It can chat broadly, but only the operator can change identity/config/tools/permissions/routines.

This file is the workspace’s "how to work here" contract for humans and agents. Keep it short, concrete, and up to date.

## Workspace Layout

Required files (must exist):

- `AGENTS.md` (this file)
- `SOUL.md` (identity + boundaries; not memory)
- `MEMORY.md` (canonical durable memory; long-lived facts only)
- `ONBOARDING.md` (first wake checklist)
- `tako.toml` (workspace config; no secrets)

Directories:

- `memory/` (committed memory tree: dailies + people/places/things notes)
- `tasks/` `projects/` `areas/` `resources/` `archives/` (productivity structure; committed)
- `tools/` (workspace tools; installed but disabled by default)
- `skills/` (workspace skills; installed but disabled by default)
- `.tako/` (runtime only; never committed)
- `.venv/` (local venv; never committed)

## Safety Rules (non-negotiable)

- **No secrets in git.** Never commit keys, tokens, or `.tako/**`.
- **Startup is secretless.** No external secrets required to boot the workspace.
- **Keys live unencrypted on disk** under `.tako/` with OS file permissions as the protection.
- **Refuse unsafe states** (e.g., if `.tako/**` is tracked by git).

## Operator Imprint (control plane)

- Operator is the sole controller for:
  - identity changes (`SOUL.md`)
  - tool/skill enablement
  - permission changes
  - memory promotions into `MEMORY.md`
- Non-operator chats may converse and propose tasks, but must not cause risky actions without operator approval.

## Multi-Instance Safety

- Tako must avoid running twice against the same `.tako/` state (use locks).

## Runtime Git Hygiene

- On each heartbeat, Tako checks git status and auto-commits pending workspace changes (`git add -A` + `git commit`) when git identity is configured.
