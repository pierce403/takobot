# ONBOARDING.md — First Wake Checklist

This is the “first wake” checklist for bringing up a new Tako instance.

## Done When

- [ ] `.tako/` runtime structure exists (`locks/`, `logs/`, `tmp/`, `state/`, `xmtp-db/`) and `.tako/keys.json` exists.
- [ ] `.venv/` exists and the engine is installed (`.venv/bin/tako` runs).
- [ ] An XMTP identity key exists locally (no external secrets required).
- [ ] Operator is imprinted (paired) and stored locally, or local-only mode is explicitly chosen.
- [ ] If pairing is attempted: outbound pairing DM is sent and operator imprint is stored without manual code copyback.
- [ ] `memory/dailies/YYYY-MM-DD.md` exists for today.
- [ ] DOSE engine initialized at `.tako/state/dose.json`, shown in UI, and biases Type 1 → Type 2 escalation sensitivity.
- [ ] PARA execution structure exists (`tasks/`, `projects/`, `areas/`, `resources/`, `archives/`) with README conventions.
- [ ] Open loops index exists at `.tako/state/open_loops.json` and is surfaced in the UI sidebar.
- [ ] Heartbeat can auto-commit pending workspace changes (auto-configuring missing local git identity when needed).
- [ ] If required setup is missing and auto-remediation fails (for example git identity), Tako emits an operator request with concrete fix steps.
- [ ] Health/doctor-detected problems are reflected as committed tasks under `tasks/` (deduped by issue).
- [ ] Auto-update policy is set (`tako.toml` `[updates].auto_apply`), defaulting to `true`.
- [ ] TUI mind indicator visibly animates during thinking/responding, and XMTP typing indicators appear when supported by runtime SDK.
- [ ] `code/` exists and is git-ignored for repo clones/code work.
- [ ] `workspace.name` in `tako.toml` matches Tako’s current identity name.
- [ ] Starter skill pack is present in `skills/` (disabled by default), including `agent-cli-inferencing`, and visible in extension listings.
- [ ] Skill/tool install pipeline works (quarantine → analyze → install disabled → enable requires operator approval).
- [ ] `SOUL.md`, `MEMORY.md`, `tako.toml`, and `FEATURES.md` exist and are consistent with current behavior.

## Steps

1) **Initialize runtime dirs**

- Create: `.tako/locks/`, `.tako/logs/`, `.tako/tmp/`, `.tako/state/`, `.tako/xmtp-db/`.

2) **Launch interactive terminal app**

- Preferred bootstrap flow:
  - `curl -fsSL https://tako.bot/setup.sh | bash`
- Next runs: `.venv/bin/tako`
- `setup.sh` creates `.venv/`, installs the engine, and materializes the workspace from engine templates.
- `tako` onboarding runs as explicit states inside the app UI:
  - `BOOTING`
  - `ASK_XMTP_HANDLE`
  - `PAIRING_OUTBOUND`
  - `PAIRED`
  - `ONBOARDING_IDENTITY`
  - `ONBOARDING_ROUTINES`
  - `RUNNING`
- During `BOOTING`, Tako runs a startup health check (instance context, lock state, and resource probes).
- During `BOOTING`, Tako scans local inference bridges (`codex`, `claude`, `gemini`) and records runtime metadata in `.tako/state/inference.json`.
- During `BOOTING`, Tako scans local inference bridges (`pi`, `ollama`, `codex`, `claude`, `gemini`) and records runtime metadata in `.tako/state/inference.json`.
- During `RUNNING`, `inference` commands can directly manage provider preference, ollama host/model, persisted API keys, and pi OAuth inventory via runtime-local `.tako/state/inference-settings.json`.
- During bootstrap, Tako installs pi runtime by default under `.tako/pi/node`; if Node/npm are missing, it bootstraps workspace-local `nvm` + Node under `.tako/nvm`.
- During runtime, Tako appends daemon/app diagnostics to `.tako/logs/runtime.log` and `.tako/logs/app.log`.
- During inference provider subprocess execution, Tako pins temp writes to `.tako/tmp/` via `TMPDIR`/`TMP`/`TEMP`.
- During `BOOTING`, inference execution remains gated; first model calls are allowed only after the first interactive chat turn.
- During `RUNNING`, identity/goals/routines prompts are delayed until inference has actually run (or can be started manually with `setup`).
- During `RUNNING`, Tako keeps heartbeat + event-log cognition active (Type 1 triage with Type 2 escalation for serious events).
- During heartbeat, Tako checks for pending git changes and auto-commits when possible.
- If heartbeat auto-commit is blocked by missing git identity, Tako auto-configures local repo identity from bot name (`<name> <name.tako.eth@xmtp.mx>`) and retries commit.
- During periodic update checks, if `[updates].auto_apply = true`, Tako applies package updates and restarts app mode automatically.
- During `RUNNING`, Tako keeps a small runtime-only DOSE model (D/O/S/E) ticking on heartbeat and reflecting mode in the UI.
- During `RUNNING`, `run` command execution uses `code/` as working directory and reports that `cwd` in responses.
- During `RUNNING`, health/doctor issues create or reuse matching follow-up tasks in `tasks/`.
- `doctor` performs offline inference diagnostics (CLI probes + recent inference-error scan) without requiring inference calls.
- During startup, Tako seeds the starter skill pack (OpenClaw-informed + `agent-cli-inferencing`) and registers it as installed-but-disabled extensions.

3) **Generate/ensure XMTP keys (local, unencrypted)**

- Create `.tako/keys.json` with `0600` permissions (best-effort).
- Do not write keys anywhere outside `.tako/`.

4) **Imprint the operator (optional during first wake)**

- Pairing is terminal-first in the interactive app (no inbound-first DM requirement).
- Tako asks in-chat for XMTP setup as the first onboarding prompt.
- If yes: Tako sends an outbound DM to that handle and assumes the recipient is ready once inbox id resolves.
- Tako stores operator metadata in `.tako/operator.json` (runtime-only; ignored by git).

5) **Pairing / handshake**

- Pairing is auto-completed in-app after successful outbound DM + inbox resolution.
- After imprint, management moves to XMTP for operator changes and commands (`help`, `status`, `doctor`, `task`, `tasks`, `done`, `morning`, `outcomes`, `compress`, `weekly`, `promote`, `update`, `web`, `run`, `reimprint`).
- Re-imprinting is still operator-only over XMTP (`reimprint CONFIRM`), then terminal onboarding pairs the next operator.

6) **Initialize today’s daily log**

- Ensure `memory/dailies/YYYY-MM-DD.md` exists.
- Never log secrets; summarize actions and decisions.

7) **Start heartbeat (safe by default)**

- Start a heartbeat loop; sensors are disabled by default.
- Store runtime-only heartbeat/cognition state under `.tako/state/`.

8) **Emit completion summary**

- After pairing, Tako keeps terminal as local cockpit (status/logs/chat/safe mode) while XMTP is the control plane.
- TUI exposes an activity panel (inference/tool/runtime traces) and clipboard helpers (`Ctrl+Shift+C`, `Ctrl+Shift+L`).
- The operator can request status via XMTP commands:
  - `help`, `status`, `doctor`, `task`, `tasks`, `done`, `morning`, `outcomes`, `compress`, `weekly`, `promote`, `update`, `web`, `run`

Notes:

- **No env vars, no CLI configuration** in the standard flow. Management is via the operator XMTP channel.
