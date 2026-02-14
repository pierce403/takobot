# takobot

Tako is **your highly autonomous octopus friend** built in **Python** with a docs-first memory system and **Type 1 / Type 2** thinking. The direction is informed by modern productivity research and stays web3-native via **XMTP** and **Ethereum** (with **Farcaster** support planned). Today, this repo includes:

- A first-class interactive terminal app main loop (`takobot`) with transcript, status bar, panels, and input box
- Startup health checks (instance shape, lock, resource probes) before entering the main loop
- Inference-provider discovery for Codex / Claude / Gemini CLIs with key-source detection
- Inference execution gate so first model call starts on the first interactive chat turn
- A background XMTP runtime with stream retries + polling fallback
- Event-log driven cognition: heartbeat + Type 1 triage + Type 2 escalation for serious signals
- XMTP control-channel handling with command router (`help`, `status`, `doctor`, `update`, `web`, `run`, `reimprint`) plus plain-text chat replies
- Built-in operator tools for webpage reads (`web <url>`) and local shell commands (`run <command>`)
- TUI activity feed (inference/tool/runtime events), clipboard copy actions, and an animated ASCII octopus panel with Takobot version + DOSE indicators
- Productivity engine v1: GTD + PARA folders (`tasks/`, `projects/`, `areas/`, `resources/`, `archives/`), daily outcomes, weekly review, progressive summaries
- Docs-first repo contract (`SOUL.md`, `VISION.md`, `MEMORY.md`, `ONBOARDING.md`)

## Docs

- Website: https://tako.bot (or `index.html` in this repo)
- Features: `FEATURES.md`
- Agent notes / lessons learned: `AGENTS.md`

## Quickstart

Bootstrap a new workspace in an empty directory, then launch Tako's interactive terminal app:

```bash
mkdir tako-workspace
cd tako-workspace
curl -fsSL https://tako.bot/setup.sh | bash
```

If no interactive TTY is available, bootstrap falls back to command-line daemon mode (`python -m takobot run`) instead of exiting.

Next runs:

```bash
.venv/bin/takobot
```

Bootstrap refuses to run in a non-empty directory unless it already looks like a Tako workspace (has `SOUL.md`, `AGENTS.md`, `MEMORY.md`, `tako.toml`).

Pairing flow:

- `takobot` always starts the interactive terminal app first.
- During onboarding, Tako asks for XMTP setup ASAP (in-chat):
  - yes: outbound DM pairing (`.eth` or `0x...`) and assumes the recipient is ready
  - no: continue onboarding locally and allow later pairing from terminal
- Identity/purpose/routine prompts are delayed until inference has actually run (or can be started manually with `setup`).
- Identity naming accepts freeform input and uses inference to extract a clean name (for example, “your name can be SILLYTAKO”).
- After pairing, XMTP becomes the primary control plane for identity/config/tools/routines (`help`, `status`, `doctor`, `update`, `web`, `run`, `reimprint`).

Productivity (GTD + PARA):

- `morning` sets today’s 3 outcomes (stored in `memory/dailies/YYYY-MM-DD.md`).
- `task <title>` creates a committed task file under `tasks/`.
- `tasks` lists open tasks (filters: `project`, `area`, `due`).
- `done <task-id>` completes a task.
- `compress` writes a progressive summary block into today’s daily log.
- `weekly` runs a weekly review report.
- `promote <note>` appends an operator-approved durable note into `MEMORY.md`.

## Architecture (minimal)

Committed (git-tracked):

- `SOUL.md`, `MEMORY.md`, `ONBOARDING.md`, `AGENTS.md`, `tako.toml`
- `FEATURES.md` (feature tracker)
- `memory/dailies/YYYY-MM-DD.md` (daily logs)
- `memory/people/`, `memory/places/`, `memory/things/` (world notes)
- `tasks/`, `projects/`, `areas/`, `resources/`, `archives/` (execution structure)
- `tools/` (workspace tools; installed but disabled by default)
- `skills/` (workspace skills; installed but disabled by default)

Runtime-only (ignored):

- `.tako/keys.json` (XMTP wallet key + DB encryption key; unencrypted, file perms only)
- `.tako/operator.json` (operator imprint metadata)
- `.tako/logs/` (runtime and terminal logs)
- `.tako/tmp/` (workspace-local temp files used by inference and bootstrap fallback)
- `.tako/xmtp-db/` (local XMTP DB)
- `.tako/state/**` (runtime state: heartbeat/cognition/etc)
- `.tako/quarantine/**` (download quarantine for skills/tools)
- `.venv/` (local virtualenv with the engine installed)

## What happens on first run

- Creates a local Python virtual environment in `.venv/`.
- Attempts to install or upgrade the engine with `pip install --upgrade takobot` (PyPI). If that fails and no engine is present, it clones source into `.tako/tmp/src/` and installs from there.
- Materializes the workspace from engine templates (`takobot/templates/**`) without overwriting existing files.
- Initializes git (if available) and commits the initial workspace.
- Generates a local key file at `.tako/keys.json` with a wallet key and DB encryption key (unencrypted; protected by file permissions).
- Creates runtime logs/temp directories at `.tako/logs/` and `.tako/tmp/`.
- Creates a local XMTP database at `.tako/xmtp-db/`.
- Launches the interactive terminal app main loop (`takobot`, default).
- Runs a startup health check to classify instance context (brand-new vs established), verify lock/safety, and inspect local resources.
- Detects available inference CLIs (`codex`, `claude`, `gemini`) and key/auth sources, then persists runtime metadata to `.tako/state/inference.json`.
- Runs onboarding as an explicit state machine inside the app, starting with XMTP channel setup.
- Shows an activity panel in the TUI so you can see inference/tool/runtime actions as they happen.
- Shows the top-right octopus panel with Takobot version and compact DOSE indicators (D/O/S/E).
- Starts heartbeat + event-log ingestion and continuously applies Type 1 triage; serious events trigger Type 2 tasks with depth-based handling.
- Type 2 escalation uses discovered inference providers with fallback across ready CLIs after the first interactive chat turn, then falls back to heuristic guidance if inference calls fail.
- If paired, starts background XMTP runtime and keeps terminal as local cockpit with plain-text chat still available.

## Configuration

There is **no user-facing configuration via environment variables or CLI flags**.

Workspace configuration lives in `tako.toml` (no secrets).

Any change that affects identity/config/tools/sensors/routines must be initiated by the operator over XMTP and (when appropriate) reflected by updating repo-tracked docs (`SOUL.md`, `MEMORY.md`, etc).

## Developer utilities (optional)

- Local checks: `.venv/bin/takobot doctor`
- One-off DM send: `.venv/bin/takobot hi --to <xmtp_address_or_ens> [--message ...]`
- Direct daemon (dev): `.venv/bin/takobot run`

## Notes

- Workspaces are git-first, but git is optional. If git is missing, Tako runs and warns that versioning is disabled.
- The daemon now retries XMTP stream subscriptions with backoff when transient group/identity stream errors occur.
- When stream instability persists, the daemon falls back to polling message history and retries stream mode after polling stabilizes.
- While running, Tako periodically checks for package updates and surfaces when `update` can apply a newer version.
- XMTP client initialization disables history sync by default for compatibility.
- Runtime event log lives at `.tako/state/events.jsonl` and is consumed by the Type 1/Type 2 cognition pipeline.
- Runtime inference metadata lives at `.tako/state/inference.json` (no raw secrets written by Tako).
- Runtime daemon logs are appended to `.tako/logs/runtime.log`; TUI transcript/system logs are appended to `.tako/logs/app.log`.
- Codex inference subprocesses are launched with sandbox/approval bypass flags so agentic chat does not falsely assume a read-only environment.
- Inference subprocess temp output and `TMPDIR`/`TMP`/`TEMP` are pinned to `.tako/tmp/` (workspace-local only).
- The bootstrap launcher rebinds stdin to `/dev/tty` for app mode, so `curl ... | bash` can still start an interactive TUI.
- XMTP support is installed with `takobot` by default; if an existing environment is missing it, run `pip install --upgrade takobot xmtp` (native build tooling such as Rust may be required).
