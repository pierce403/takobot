# ONBOARDING.md — First Wake Checklist

This file is the operator’s checklist for bringing a new Tako workspace to a healthy, paired state.

## Quickstart

- Start Tako: `.venv/bin/takobot`
- Tako boots into an interactive terminal UI (main loop).

## On First Boot

- [ ] Health check ran (workspace + runtime dirs + lock).
- [ ] Inference runtime discovered (Codex / Claude / Gemini CLI if installed).
- [ ] Daily log created for today in `memory/dailies/YYYY-MM-DD.md`.
- [ ] DOSE engine initialized (`.tako/state/dose.json`) and visible in the UI.
- [ ] Productivity folders exist (`tasks/`, `projects/`, `areas/`, `resources/`, `archives/`).
- [ ] Open loops index initialized (`.tako/state/open_loops.json`).
- [ ] Heartbeat git auto-commit works (`git add -A` + `git commit`) when `user.name`/`user.email` are configured.
- [ ] If required setup is missing (for example git identity), Tako asks the operator with concrete fix steps.
- [ ] Health/doctor-detected problems are reflected as committed follow-up tasks under `tasks/` (deduped by issue).
- [ ] Auto-update policy is configured in `tako.toml` (`[updates].auto_apply`, default `true`).
- [ ] TUI mind indicator animates while thinking/responding; XMTP typing indicators are used when SDK/runtime support exists.
- [ ] `code/` exists and is git-ignored for repo clones and code work.
- [ ] `workspace.name` in `tako.toml` matches Tako’s active identity name.
- [ ] Starter skill pack is present in `skills/` (disabled by default), including `agent-cli-inferencing`, and appears in extension listings.
- [ ] `doctor` runs offline inference diagnostics (CLI probes + recent inference-error scan) without requiring inference calls.

## Operator Control Channel (XMTP)

- [ ] Provide operator XMTP handle in the TUI when prompted (or run `pair`).
- [ ] Confirm messages are flowing over XMTP.
- [ ] After imprint: operator-only boundaries apply for identity/config/tools/permissions/routines.

## Skills / Tools

- [ ] Install pipeline works (quarantine → analyze → install disabled → enable with operator approval).
- [ ] Enabled extensions respect permissions (`tako.toml` defaults; explicit grants required).
