# Tako — Features

## Features

### Docs-first repo contract
- **Stability**: stable
- **Description**: The repo documents identity, invariants, onboarding, and durable memory as first-class artifacts.
- **Properties**:
  - Root docs exist: `AGENTS.md`, `SOUL.md`, `VISION.md`, `MEMORY.md`, `ONBOARDING.md`.
  - Committed knowledge lives under `memory/` (daily logs + world notes); `memory/MEMORY.md` is a compatibility pointer.
  - Feature state is tracked in `FEATURES.md`.
  - Website copy lives in `index.html`.
- **Test Criteria**:
  - [x] Root contract docs exist and are coherent.

### Legacy repo runner (`tako.sh`)
- **Stability**: deprecated (dev only)
- **Description**: Repo-local launcher used during engine development.
- **Properties**:
  - Uses `uv` to create/manage a virtualenv at `.venv/` (repo-local).
  - Installs dependencies from `requirements.txt` via `uv pip` when needed.
  - Defaults to `python -m takobot app`.
  - Exposes developer utilities (`doctor`, `hi`).
- **Test Criteria**:
  - [x] `./tako.sh` starts the interactive app (dev path).

### Workspace bootstrap (`setup.sh`)
- **Stability**: in-progress
- **Description**: Safe bootstrap for a new workspace via `curl | bash`, ending in the interactive terminal app when a TTY is available.
- **Properties**:
  - Refuses to run unless the directory is empty, or already looks like a Tako workspace (`SOUL.md`, `AGENTS.md`, `MEMORY.md`, `tako.toml`).
  - Creates `.venv/` in the workspace directory.
  - Attempts `pip install --upgrade takobot`. If PyPI install fails and no engine is already present, clones source into `.tako/tmp/src/` and installs from there.
  - Engine packaging includes XMTP as a required dependency, so plain `pip install takobot` installs XMTP bindings by default.
  - Materializes workspace templates from the installed engine (`takobot/templates/**`) without overwriting user files; logs template drift to today’s daily log.
  - Initializes git on `main` + `.gitignore` + first commit if git is available; warns if git is missing.
  - Launches `.venv/bin/takobot` (TUI main loop) and rebinds stdin to `/dev/tty` when started via a pipe.
  - Falls back to `.venv/bin/takobot run` (stdout CLI daemon mode) when no interactive TTY is available.
- **Test Criteria**:
  - [ ] In an empty dir with an interactive TTY, `curl -fsSL https://tako.bot/setup.sh | bash` creates `.venv/`, materializes workspace files, initializes git on `main`, and launches the TUI.
  - [ ] In a non-interactive environment, the same command falls back to stdout daemon mode instead of exiting with a TTY error.
  - [ ] Re-running `setup.sh` is idempotent and does not overwrite edited files.

### CLI entrypoints (`takobot`, `python -m takobot`, `tako.py`)
- **Stability**: in-progress
- **Description**: `takobot` defaults to interactive app mode; subcommands remain for dev/automation paths.
- **Properties**:
  - `takobot` / `python -m takobot` launch `app` mode by default (interactive terminal main loop).
  - `takobot app` starts the TUI explicitly.
  - `takobot run` remains available for direct daemon loop (dev path).
  - Daemon/runtime performs periodic update checks and logs when a newer package version is available.
  - `takobot run` automatically retries XMTP message stream subscriptions with backoff on transient stream failures.
  - If stream failures persist, `takobot run` falls back to polling message history until stream mode stabilizes.
  - App onboarding performs terminal-first outbound pairing and then starts runtime tasks.
  - `takobot bootstrap` remains as a legacy/bootstrap utility path.
  - `takobot doctor` and `takobot hi` exist as developer utilities.
  - `tako.py` remains as a backwards-compatible wrapper.
- **Test Criteria**:
  - [x] `python -m takobot doctor` runs and reports missing dependencies clearly.
  - [x] `python tako.py --to <addr>` invokes the `hi` command path.

### Interactive terminal app main loop (`takobot app`)
- **Stability**: in-progress
- **Description**: A persistent full-screen terminal UI acts as the primary operator-facing runtime loop.
- **Properties**:
  - Includes a scrolling transcript, status bar, input box, and structured side panels (tasks/memory/sensors).
  - Runs startup health checks (instance context, lock state, writable paths, dependency/network probes) before onboarding.
  - Detects inference providers from local CLI installs (`codex`, `claude`, `gemini`) and discovers auth/key sources at startup.
  - Keeps inference execution gated until the first interactive chat turn (onboarding turn for new sessions).
  - Runs onboarding as explicit states: `BOOTING`, `ASK_XMTP_HANDLE`, `PAIRING_OUTBOUND`, `PAIRED`, `ONBOARDING_IDENTITY`, `ONBOARDING_ROUTINES`, `RUNNING`.
  - Prompts for XMTP control-channel setup first (ASAP), and delays identity/routine prompts until inference has actually run.
  - Name capture in identity onboarding accepts freeform phrases and uses inference to extract a clean name token (not entire sentence).
  - In running chat, the operator can rename Tako inline with a natural message (e.g. “call yourself SILLYTAKO”) and the app persists the parsed name into `SOUL.md`.
  - Uses a playful octopus voice in onboarding transcript copy.
  - Runs heartbeat + event-log ingestion under UI orchestration, then applies Type 1 triage continuously.
  - Escalates serious events into Type 2 tasks with depth-aware handling.
  - Type 2 invokes discovered inference providers with automatic fallback across ready CLIs.
  - Runs XMTP daemon loop as a background task when paired.
  - Keeps terminal plain-text chat available in running mode, even when XMTP is connected/paired.
  - Includes an activity panel with inference/tool/runtime trace lines.
  - Streams in-progress inference output into a scrollable "bubble stream" panel above the input box (Cursor/Claude style).
  - Supports clipboard-friendly controls (`Ctrl+Shift+C` transcript, `Ctrl+Shift+L` last line, paste sanitization).
  - Shows an animated top-right ASCII octopus level panel in the sidebar.
  - Supports local-only mode before pairing and safe-mode pause/resume controls.
  - Restores text-input focus after terminal resize/blur to keep chat entry stable.
  - Filters terminal control-sequence noise from input/transcript rendering.
  - Rebinds app stdin to `/dev/tty` in launcher flow so `curl ... | bash` startup doesn't inherit a pipe for TUI input.
  - Surfaces operational failures as concise in-UI error cards with suggested next actions.
- **Test Criteria**:
  - [x] Running `takobot` opens app mode by default (no required subcommand).
  - [x] Startup logs include a health-check summary (brand-new vs established + resource checks).
  - [x] XMTP setup prompt appears first in-chat on unpaired startup.
  - [x] Identity + routine onboarding prompts are delayed until inference is active (or manually triggered).
  - [x] Freeform naming inputs (e.g. “your name can be SILLYTAKO”) persist only the parsed name in `SOUL.md`.
  - [x] In running chat, “call yourself SILLYTAKO” updates `SOUL.md` without entering a special setup mode.
  - [x] Outbound XMTP pairing can auto-complete without code copyback confirmation.
  - [x] Serious runtime/health events are escalated from Type 1 triage into Type 2 analysis.
  - [x] Runtime can report Codex/Claude/Gemini CLI+auth discovery status via `inference` command.
  - [x] Type 2 does not call model inference before the first interactive user turn.
  - [x] Type 2 keeps operating with heuristic fallback when provider invocations fail.
  - [x] After pairing, non-command text in terminal still receives chat replies.
  - [x] Activity panel shows inference/tool/runtime actions.
  - [x] Terminal chat inference streams output to the bubble-stream panel while generating.
  - [x] Resize/blur does not leave the app without a usable text-input focus.
  - [x] `curl ... | bash` launch path enters app mode with usable TTY input (no pipe-inherited garble).

### DOSE cognitive state (D/O/S/E)
- **Stability**: in-progress
- **Description**: Runtime-only simulated DOSE (Dopamine/Oxytocin/Serotonin/Endorphins) state that biases behavior without overriding operator boundaries.
- **Properties**:
  - Stored in `.tako/state/dose.json` (runtime-only; ignored by git).
  - Deterministic: decays toward baselines on heartbeat ticks and clamps each channel to `[0,1]`.
  - Updated from all recorded events via a single hook in the app event recorder.
  - Displayed in the TUI status bar and sidebar sensor panel.
  - Biases Type 1 → Type 2 escalation sensitivity (more cautious when low S/E; more tolerant when high S/E).
- **Test Criteria**:
  - [ ] Launch `takobot` shows DOSE values + label in the UI.
  - [ ] A simulated runtime/pairing failure reduces S/E and shifts the label toward `stressed`.
  - [ ] After calm heartbeats, DOSE decays back toward baseline.
  - [ ] Type 1 → Type 2 escalation threshold changes measurably with DOSE (critical/error still escalate).
  - [ ] `.tako/state/dose.json` persists across restarts and is never committed.

### Productivity engine v1 (GTD + PARA + progressive summarization)
- **Stability**: in-progress
- **Description**: A committed execution structure (PARA) plus GTD capture/clarify/next-actions, with daily outcomes and progressive summaries.
- **Properties**:
  - PARA directories exist (committed): `projects/`, `areas/`, `resources/`, `archives/`, `tasks/` (each with a README).
  - Tasks live under `tasks/*.md` with YAML frontmatter (`id`, `title`, `status`, `project`, `area`, `created`, `updated`, `due`, `tags`, `energy`).
  - Terminal app exposes productivity commands even when XMTP is connected: `task`, `tasks`, `done`, `morning`, `outcomes`, `compress`, `weekly`, `promote`.
  - XMTP operator commands support the same core flows for remote control.
  - Daily outcomes ("3 for today") live in `memory/dailies/YYYY-MM-DD.md` and are editable via commands.
  - Runtime-only open loops index lives at `.tako/state/open_loops.json` and is surfaced in the TUI sidebar.
  - `compress` appends/updates a structured progressive summary block in today’s daily log (Type2 with inference when available; heuristic fallback).
  - `weekly` review surfaces stale tasks and projects missing a next action, and prompts for archive + promote.
  - DOSE biases planning hints (e.g., stressed tides reduce churn; high D suggests exploration).
- **Test Criteria**:
  - [ ] Running `takobot` on a new day creates today’s daily log and offers `morning` if outcomes are blank.
  - [ ] Sidebar shows open tasks + open loops count and oldest age.
  - [ ] `task <title>` creates a file under `tasks/` and appends a daily log note.
  - [ ] `tasks` lists open tasks and filters by project/area/due.
  - [ ] `done <id>` marks a task complete and appends a daily log note.
  - [ ] `weekly` surfaces stale tasks and projects missing next actions and prompts for archive + promote.
  - [ ] `compress` adds a progressive summary block to today’s daily log.
  - [ ] `promote <note>` appends an operator-approved durable note to `MEMORY.md`.

### Skills / tools install pipeline (quarantine + analysis + enablement gate)
- **Stability**: in-progress
- **Description**: Install workspace extensions from URLs with a quarantine-first pipeline and a default-deny enablement gate.
- **Properties**:
  - `install skill <url>` and `install tool <url>` download into `.tako/quarantine/<id>/` (no execution).
  - Static analysis produces a report (provenance, hashes, risky API scan, permission diff vs `tako.toml`).
  - Operator chooses to accept/reject the quarantine item.
  - Accepted installs land in `skills/<name>/` or `tools/<name>/` but remain disabled by default.
  - `enable skill <name>` / `enable tool <name>` re-check hashes and permissions before enabling.
  - If files change after install (hash mismatch), enablement refuses until re-reviewed.
- **Test Criteria**:
  - [ ] `install skill <url>` creates a quarantine entry and prints a security report.
  - [ ] `install accept <id>` installs the skill disabled and records a daily log note.
  - [ ] Modifying an installed file causes `enable ...` to refuse due to hash mismatch.
  - [ ] `draft skill <name>` / `draft tool <name>` create disabled extension skeletons in the workspace.

### Local runtime keys (`.tako/keys.json`)
- **Stability**: stable
- **Description**: Keys are stored locally (unencrypted) under `.tako/` with OS file permissions as the protection.
- **Properties**:
  - Creates `.tako/keys.json` with `wallet_key` and `db_encryption_key` if missing.
  - Attempts to set file permissions to `0600` (best-effort).
  - No user-facing env-var overrides; keys are loaded from disk at runtime.
  - Migrates legacy `.tako/config.json` → `.tako/keys.json` when present.
  - Refuses to run if `.tako/**` is tracked by git.
- **Test Criteria**:
  - [x] If `.tako/keys.json` is missing, Tako creates it.
  - [x] If `.tako/config.json` exists, Tako reuses those keys.

### Recipient resolution (address + ENS)
- **Stability**: stable
- **Description**: Accepts `0x…` addresses directly and resolves `.eth` names to addresses.
- **Properties**:
  - `0x…` recipients are treated as already-resolved addresses.
  - ENS resolution tries configured RPC endpoints, then falls back to a public resolver.
- **Test Criteria**:
  - [x] A `0x…` recipient is returned unchanged.
  - [x] A `.eth` recipient attempts ENS resolution and falls back before erroring.

### One-off XMTP DM send (`takobot hi`)
- **Stability**: stable
- **Description**: Creates an XMTP client, opens a DM, and sends a message.
- **Properties**:
  - Default message includes the machine hostname.
  - `--message` overrides the default message.
  - XMTP client options disable history sync by default.
- **Test Criteria**:
  - [x] Without `--message`, a default “hi from <hostname> (tako)” message is used.

### Local XMTP DB storage + reset
- **Stability**: stable
- **Description**: Stores XMTP state locally and supports a “nuke and rebuild” reset.
- **Properties**:
  - DB files live under `.tako/xmtp-db/` and are named `xmtp-{env}-{inbox_id}.db3`.
- **Test Criteria**:
  - [x] `.tako/xmtp-db/` is created automatically if missing.

### XMTP settings (operator-managed)
- **Stability**: planned
- **Description**: Manage XMTP endpoints and sync behavior over the operator XMTP channel (no env vars).
- **Properties**:
  - Endpoint changes are initiated by the operator over XMTP.
  - Settings are stored under `.tako/` (runtime-only) and never committed.
- **Test Criteria**:
  - [ ] Operator can change XMTP settings over XMTP and the daemon applies them safely.

### Farcaster integration (operator-managed)
- **Stability**: planned
- **Description**: Add Farcaster ingress/egress without bypassing operator-imprint safety rules.
- **Properties**:
  - Enable/disable and policy changes are operator-only.
  - Runtime integration state lives under `.tako/state/` and is never committed.
  - Non-operator traffic cannot mutate identity/config/tools/routines.
- **Test Criteria**:
  - [ ] Operator can enable or disable Farcaster integration safely.
  - [ ] Farcaster messages are handled without bypassing operator authorization boundaries.

### Operator imprint (`.tako/operator.json`)
- **Stability**: in-progress
- **Description**: Tako stores a single operator (controller) imprinted over XMTP and refuses silent reassignment.
- **Properties**:
  - Pairing is terminal-first in app mode: Tako sends an outbound DM and auto-assumes readiness once recipient inbox id resolves.
  - Stores `operator_inbox_id` under `.tako/operator.json` (runtime-only; ignored by git).
  - Re-imprinting requires an explicit operator command over XMTP (`reimprint CONFIRM`), then terminal onboarding pairs a new operator.
  - Operator can run `update` over XMTP to perform a guarded fast-forward self-update.
  - Operator can run `web <url>` and `run <command>` over XMTP.
  - Plain-text XMTP messages are handled as chat (inference-backed when available) while command-style messages route to command handlers.
- **Test Criteria**:
  - [x] `takobot` app mode can complete first pairing without requiring inbound XMTP stream health.
  - [x] Once paired, only the operator inbox can run `status` / `doctor`.
  - [x] Operator can run `update` / `update check` over XMTP and receive result details.
  - [x] Operator can run `web` / `run` over XMTP and receive output.
  - [x] Operator plain-text XMTP messages no longer return `Unknown command`; they receive chat replies.

### Daily logs (`memory/dailies/YYYY-MM-DD.md`)
- **Stability**: in-progress
- **Description**: OpenClaw-style daily logs are committed under `memory/dailies/`, while runtime state stays under `.tako/`.
- **Properties**:
  - `takobot` app mode and `takobot run` ensure today’s daily log exists.
  - Daily log templates warn against secrets.
- **Test Criteria**:
  - [x] Running `takobot` or `takobot run` creates `memory/dailies/YYYY-MM-DD.md` if missing.

### Tool discovery (`tools/*/tool.py`)
- **Stability**: in-progress
- **Description**: Tools live under `tools/` and are discoverable via a loader.
- **Properties**:
  - Loader scans for `tools/<name>/tool.py` exporting `TOOL_MANIFEST`.
  - Tool manifests declare permissions.
- **Test Criteria**:
  - [x] Loader can discover at least one tool (`tools/memory_append/tool.py`).

### Multi-instance lock
- **Stability**: in-progress
- **Description**: Prevent multiple Tako processes from using the same `.tako/` directory.
- **Properties**:
  - Uses an exclusive lock at `.tako/locks/tako.lock` (platform requires `fcntl`).
- **Test Criteria**:
  - [ ] Second instance fails fast with a clear error.

### Operator-only command authorization
- **Stability**: in-progress
- **Description**: Enforce that only the operator can modify identity/config/tools/routines.
- **Properties**:
  - Reject non-operator attempts to steer identity/config with a firm boundary.
- **Test Criteria**:
  - [x] Non-operator “controller” commands are refused (basic boundary response for obvious command attempts).

### Tasks + calendar storage (markdown)
- **Stability**: planned
- **Description**: Store tasks/calendar as committed markdown with YAML frontmatter.
- **Properties**:
  - `tasks/*.md` and `calendar/*.md` are git-tracked.
- **Test Criteria**:
  - [ ] CRUD tools can create/read/update entries deterministically.

### Sensors framework (disabled by default)
- **Stability**: planned
- **Description**: Poll-based sensors with significance gating and runtime-only state.
- **Properties**:
  - Sensor state stored under `.tako/state/sensors/<name>.json`.
- **Test Criteria**:
  - [ ] Disabled sensors produce no events.

### Cognitive state (Type 1 / Type 2)
- **Stability**: in-progress
- **Description**: Runtime-only cognition loop that triages events with Type 1 and escalates serious signals to Type 2 depth passes.
- **Properties**:
  - Event log is stored at `.tako/state/events.jsonl` (ignored).
  - Type 1 continuously consumes and evaluates event-log items.
  - Type 2 is triggered for serious events with `light` / `medium` / `deep` depth.
- **Test Criteria**:
  - [x] Startup health-check issues can trigger Type 2 escalation.
  - [x] Runtime error events can trigger Type 2 escalation.

### “Eat the crab” importer
- **Stability**: planned
- **Description**: Import OpenClaw-style layouts into the new contract (SOUL/memory/tools).
- **Properties**:
  - Produces an `IMPORT_REPORT.md`.
- **Test Criteria**:
  - [ ] Imports a sample layout without losing provenance.
