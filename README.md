# takobot

Tako is **your highly autonomous octopus friend** built in **Python** with a docs-first memory system and **Type 1 / Type 2** thinking. By default, Tako is intentionally curious about the world and pushes toward evidence-backed answers. The direction is informed by modern productivity research and stays web3-native via **XMTP** and **Ethereum** (with **Farcaster** support planned). Today, this repo includes:

- A first-class interactive terminal app main loop (`takobot`) with transcript, status bar, panels, and input box
- Startup health checks (instance shape, lock, resource probes) before entering the main loop
- Inference-provider discovery with ordered fallback (`pi`, `ollama`, Codex, Claude, Gemini) and key-source detection
- Default pi tooling install in workspace (`.tako/pi/node`), with local `nvm` bootstrap under `.tako/nvm` when host Node/npm are missing
- Inference execution gate so first model call starts on the first interactive chat turn
- OpenClaw-style conversation management: per-session JSONL transcripts under `.tako/state/conversations/` with bounded history windows injected into prompts
- A background XMTP runtime with stream retries + polling fallback
- Event-log driven cognition: heartbeat + Type 1 triage + Type 2 escalation for serious signals
- Heartbeat-time git hygiene: if workspace changes are pending, Tako stages (`git add -A`) and commits automatically, and verifies the repo is clean after commit
- Missing-setup prompts: when required config/deps are missing and auto-remediation fails, Tako asks the operator with concrete fix steps
- Runtime problem capture: detected warnings/errors are converted into committed `tasks/` items for follow-up
- Animated "mind" indicator in the TUI (status/sidebar/stream/octopus panel) while Tako is thinking or responding
- Auto-update setting (`tako.toml` → `[updates].auto_apply = true` by default) with in-app apply + self-restart when a new package release is detected
- XMTP control-channel handling with command router (`help`, `status`, `doctor`, `update`, `web`, `run`, `reimprint`) plus plain-text chat replies
- Built-in operator tools for webpage reads (`web <url>`) and local shell commands (`run <command>`)
- Code work isolation: shell command execution runs in `code/` (git-ignored) so repo clones and code sandboxes stay out of workspace history
- Built-in starter skills are auto-seeded into `skills/` (disabled): OpenClaw top-10, priority `skill-creator` + MCP-focused `mcporter-mcp`, and an `agent-cli-inferencing` guide that nudges toward `@mariozechner/pi-ai`
- TUI activity feed (inference/tool/runtime events), clipboard copy actions, and an animated ASCII octopus panel with Takobot version + DOSE indicators
- TUI input history recall: press `↑` / `↓` in the input box to cycle previously submitted local messages
- Slash-command UX in the TUI: typing `/` opens a dropdown under the input field with command shortcuts; includes `/models` for pi/inference auth config, `/upgrade` as update alias, `/stats` for runtime counters, and `/dose ...` for direct DOSE level tuning
- TUI command entry supports `Tab` autocomplete for command names (with candidate cycling on repeated `Tab`)
- Bubble stream now shows the active request focus + elapsed time while thinking/responding so long responses stay transparent
- Productivity engine v1: GTD + PARA folders (`tasks/`, `projects/`, `areas/`, `resources/`, `archives/`), daily outcomes, weekly review, progressive summaries
- Docs-first repo contract (`SOUL.md`, `VISION.md`, `MEMORY.md`, `ONBOARDING.md`)
- OpenClaw-style docs tree in `docs/` (`start/`, `concepts/`, `reference/`)

## Docs

- Website: https://tako.bot (or `index.html` in this repo)
- Docs directory: `docs/` (OpenClaw-style `start/`, `concepts/`, `reference/`)
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
- `.tako/nvm/` (workspace-local Node runtime via nvm when system Node is unavailable)
- `.tako/npm-cache/` (workspace-local npm cache for tool installs)
- `.tako/xmtp-db/` (local XMTP DB)
- `.tako/state/**` (runtime state: heartbeat/cognition/etc)
- `.tako/quarantine/**` (download quarantine for skills/tools)
- `.venv/` (local virtualenv with the engine installed)

## What happens on first run

- Creates a local Python virtual environment in `.venv/`.
- Attempts to install or upgrade the engine with `pip install --upgrade takobot` (PyPI). If that fails and no engine is present, it clones source into `.tako/tmp/src/` and installs from there.
- Installs local pi runtime in `.tako/pi/node` (`@mariozechner/pi-ai` + `@mariozechner/pi-coding-agent`) by default; if Node/npm are missing, bootstrap installs workspace-local `nvm` + Node under `.tako/nvm` first.
- Materializes the workspace from engine templates (`takobot/templates/**`) without overwriting existing files.
- Initializes git (if available) and commits the initial workspace.
- If initial git commit is blocked by missing identity, bootstrap sets repo-local fallback identity from `workspace.name` (email format: `<name>.tako.eth@xmtp.mx`) and retries.
- Ensures a git-ignored `code/` directory exists for temporary repo clones/code work.
- Generates a local key file at `.tako/keys.json` with a wallet key and DB encryption key (unencrypted; protected by file permissions).
- Creates runtime logs/temp directories at `.tako/logs/` and `.tako/tmp/`.
- Creates a local XMTP database at `.tako/xmtp-db/`.
- Launches the interactive terminal app main loop (`takobot`, default).
- Runs a startup health check to classify instance context (brand-new vs established), verify lock/safety, and inspect local resources.
- If required setup is missing, emits an in-app operator request with direct remediation steps.
- Detects available inference CLIs (`pi`, `ollama`, `codex`, `claude`, `gemini`) and key/auth sources, then persists runtime metadata to `.tako/state/inference.json`.
- Detects local `pi` runtime first (then `ollama`/`codex`/`claude`/`gemini`) and runs inference with ordered provider fallback.
- Loads auto-update policy from `tako.toml` (`[updates].auto_apply`, default `true`).
- Runs onboarding as an explicit state machine inside the app, starting with XMTP channel setup.
- Shows an activity panel in the TUI so you can see inference/tool/runtime actions as they happen.
- Shows the top-right octopus panel with Takobot version and compact DOSE indicators (D/O/S/E).
- Starts heartbeat + event-log ingestion and continuously applies Type 1 triage; serious events trigger Type 2 tasks with depth-based handling.
- Type 2 escalation uses discovered inference providers with fallback across ready CLIs after the first interactive chat turn, then falls back to heuristic guidance if inference calls fail.
- Seeds starter skills into `skills/` and registers them as installed-but-disabled runtime extensions.
- If paired, starts background XMTP runtime and keeps terminal as local cockpit with plain-text chat still available.

## Configuration

There is **no user-facing configuration via environment variables or CLI flags**.

Workspace configuration lives in `tako.toml` (no secrets).
- `workspace.name` is the bot’s identity name and is kept in sync with rename/identity updates.
- Auto-update policy lives in `[updates]` (`auto_apply = true` by default). In the TUI: `update auto status|on|off`.
- Use `config` (local TUI) or XMTP `config` to get a guided explanation of all `tako.toml` options and current values.
- Inference auth/provider settings are runtime-local in `.tako/state/inference-settings.json` and can be managed directly with `inference ...` commands (provider preference, ollama host/model, API keys, pi OAuth inventory).
- `doctor` runs local/offline inference diagnostics (CLI probes + recent inference error scan) and does not depend on inference being available.
- Extension downloads are always HTTPS; non-HTTPS is not allowed.
- Security permission defaults for enabled extensions are now permissive by default (`network/shell/xmtp/filesystem = true`), and can be tightened in `tako.toml`.

Any change that affects identity/config/tools/sensors/routines must be initiated by the operator over XMTP and (when appropriate) reflected by updating repo-tracked docs (`SOUL.md`, `MEMORY.md`, etc).

## Developer utilities (optional)

- Local checks: `.venv/bin/takobot doctor`
- One-off DM send: `.venv/bin/takobot hi --to <xmtp_address_or_ens> [--message ...]`
- Direct daemon (dev): `.venv/bin/takobot run`
- Test suite: `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- Feature checklist guard: `tests/test_features_contract.py` parses every `FEATURES.md` test criterion and enforces probe coverage so checklist drift is caught in CI/local runs.
- Research-note scenario: `tests/test_research_workflow.py` validates that a research topic can fetch sources and write structured daily notes.

## Notes

- Workspaces are git-first, but git is optional. If git is missing, Tako runs and warns that versioning is disabled.
- The daemon now retries XMTP stream subscriptions with backoff when transient group/identity stream errors occur.
- When stream instability persists, the daemon falls back to polling message history and retries stream mode after polling stabilizes.
- While running, Tako periodically checks for package updates. With `updates.auto_apply = true`, the TUI applies the update and restarts itself.
- XMTP client initialization disables history sync by default for compatibility.
- Runtime event log lives at `.tako/state/events.jsonl` and is consumed by the Type 1/Type 2 cognition pipeline.
- Runtime inference metadata lives at `.tako/state/inference.json` (no raw secrets written by Tako).
- Runtime daemon logs are appended to `.tako/logs/runtime.log`; TUI transcript/system logs are appended to `.tako/logs/app.log`.
- Codex inference subprocesses are launched with sandbox/approval bypass flags so agentic chat does not falsely assume a read-only environment.
- Inference subprocess temp output and `TMPDIR`/`TMP`/`TEMP` are pinned to `.tako/tmp/` (workspace-local only).
- Chat context is persisted in `.tako/state/conversations/` (`sessions.json` + per-session JSONL transcripts) and recent turns are injected into prompt context.
- On each heartbeat, Tako checks git status and auto-commits pending workspace changes (`git add -A` + `git commit`) when possible.
- If git auto-commit encounters missing git identity, Tako auto-configures repo-local identity from the bot name (`<name> <name.tako.eth@xmtp.mx>`) and retries the commit.
- When runtime/doctor detects actionable problems (git/inference/dependency/runtime), Tako opens/maintains matching tasks under `tasks/` automatically.
- The bootstrap launcher rebinds stdin to `/dev/tty` for app mode, so `curl ... | bash` can still start an interactive TUI.
- XMTP replies now use a typing indicator when supported by the installed XMTP SDK/runtime.
- Transcript view is now selectable (read-only text area), so mouse highlight/copy works directly in compatible terminals.
- Input box supports shell-style history recall (`↑` / `↓`) for previously submitted local messages.
- Web reads are fetched with the built-in `web` tool and logged into the daily notes stream for traceability.
- XMTP support is installed with `takobot` by default; if an existing environment is missing it, run `pip install --upgrade takobot xmtp` (native build tooling such as Rust may be required).
