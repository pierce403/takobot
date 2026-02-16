# VISION.md — Tako Invariants (1 page)

These invariants should remain true as the implementation evolves.

## Terminal Main Loop + XMTP Control Plane

- Running `tako` starts an interactive terminal app that is the primary runtime loop.
- Before pairing, terminal app onboarding is the control path.
- After pairing, XMTP is the remote operator control channel for identity/config/tools/routines changes.
- Terminal remains a full local operator control surface for status, logs, chat, tool actions, config changes, and safe-mode controls.

Implications:

- No user-facing configuration via environment variables.
- No required subcommands for normal operation (`tako` launches app mode directly).

## Operator Imprint

- Tako has one operator (controller).
- Operator-only changes include: identity (`SOUL.md`), permissions, tools/sensors, routines, and durable memory (`MEMORY.md`).
- Non-operator chats are allowed, but are constrained to low-risk conversation and suggestions.

## Multi-instance Safety

- Multiple Tako instances must not corrupt shared state.
- Use locks under `.tako/locks/` to prevent duplicate daemons using the same `.tako/` directory.

## Tools / Sensors / Skills

- Tools live in `tools/` and are discoverable via a loader.
- Tools declare permissions (read/write/network/comms) and are disabled-by-default unless operator enables them.
- Sensors are disabled by default; when enabled, they must gate output by significance.

## Type 1 / Type 2 Thinking + Cognitive State

- Maintain a local, runtime-only cognitive state under `.tako/state/` (not committed).
- Default to Type 1 for routing/triage/drafts.
- Switch to Type 2 when the operator asks, when changing identity/config, or before risky operations.

## Git-first, No Encryption in Working Directory

- The repo is the source of truth for docs and trackers.
- Do not store encrypted blobs or secret vaults in the working directory.
- Keys needed for runtime may exist unencrypted under `.tako/` with OS permissions as protection, and must be ignored by git.
