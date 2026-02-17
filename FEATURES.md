# Tako — Features

## Features

### Docs-first repo contract
- **Stability**: stable
- **Description**: The repo documents identity, invariants, onboarding, and durable memory as first-class artifacts.
- **Properties**:
  - Root docs exist: `AGENTS.md`, `SOUL.md`, `VISION.md`, `MEMORY.md`, `ONBOARDING.md`.
  - `MEMORY.md` is a memory-system frontmatter spec at repo root and is injected into prompt context.
  - Committed memory markdown lives under `memory/` (`dailies/`, `world/`, `reflections/`, `contradictions/`); `memory/MEMORY.md` is a compatibility pointer.
  - Feature state is tracked in `FEATURES.md`.
  - Feature checklist coverage is enforced by `tests/test_features_contract.py` (every criterion is parsed and mapped to executable probes).
  - Website copy lives in `index.html`.
- **Test Criteria**:
  - [x] Root contract docs exist and are coherent.

### Legacy repo runner (`tako.sh`)
- **Stability**: deprecated (dev only)
- **Description**: Repo-local launcher used during engine development.
- **Properties**:
  - Packaged as an installed shell script so deployed environments can invoke `tako.sh` directly.
  - Runs in dual mode: repo checkout mode keeps uv/venv bootstrap behavior; deployed mode dispatches to installed `takobot`.
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
  - Installs local pi runtime under `.tako/pi/node` (`@mariozechner/pi-ai` + `@mariozechner/pi-coding-agent`) by default.
  - If Node/npm are missing, bootstraps workspace-local `nvm` + Node under `.tako/nvm` and keeps npm cache under `.tako/npm-cache`.
  - Engine packaging includes XMTP as a required dependency, so plain `pip install takobot` installs XMTP bindings by default.
  - Materializes workspace templates from the installed engine (`takobot/templates/**`) without overwriting user files; logs template drift to today’s daily log.
  - Initializes git on `main` + `.gitignore` + first commit if git is available; warns if git is missing.
  - Launches `.venv/bin/takobot` (TUI main loop) and rebinds stdin to `/dev/tty` when started via a pipe.
  - Falls back to `.venv/bin/takobot run` (stdout CLI daemon mode) when no interactive TTY is available.
- **Test Criteria**:
  - [x] Setup script bootstraps workspace-local nvm/node when npm is missing and keeps npm cache in `.tako/`.
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
  - `takobot run` appends daemon/runtime lines to `.tako/logs/runtime.log`.
  - Daemon heartbeat performs git auto-commit for pending workspace changes (`git add -A` + `git commit`).
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
  - Detects required local `pi` runtime/auth at startup (and still reports other provider probes for diagnostics).
  - Enforces pi-only inference execution (no non-pi fallback for model calls).
  - Supports runtime-local inference configuration via `inference ...` commands (provider preference `auto|pi`, persisted API keys, pi OAuth inventory).
  - Supports assisted pi login in TUI via `inference login`, relaying login prompts and accepting operator replies with `inference login answer <text>`.
  - Inference execution is pi-runtime-only; non-pi CLIs are diagnostic-only and never used for model reply generation.
  - Keeps inference execution gated until the first interactive chat turn (onboarding turn for new sessions).
  - Runs onboarding as explicit states: `BOOTING`, `ASK_XMTP_HANDLE`, `PAIRING_OUTBOUND`, `PAIRED`, `ONBOARDING_IDENTITY`, `ONBOARDING_ROUTINES`, `RUNNING`.
  - Hatchling onboarding is stage-aware and ordered: name, purpose, then XMTP handle yes/no.
  - On onboarding completion, stage transitions from `hatchling` to `child`, updates `tako.toml`, and logs the transition in `memory/dailies/`.
  - Name capture in identity onboarding accepts freeform phrases and uses inference to extract a clean name token (not entire sentence).
  - In running chat, the operator can rename Tako inline with a natural message (e.g. “call yourself SILLYTAKO”) and the app persists the parsed name into `SOUL.md`.
  - Uses a playful octopus voice in onboarding transcript copy.
  - Runs a runtime service (heartbeat + exploration + sensors) under UI orchestration, then applies Type 1 triage continuously.
  - Uses an in-memory EventBus that writes `.tako/state/events.jsonl` for audit while dispatching events directly to Type 1 queues (no JSONL polling loop).
  - Includes world-watch sensors for RSS/Atom monitoring (`RSSSensor`) plus child-stage random curiosity exploration (`CuriositySensor`) across Reddit/Hacker News/Wikipedia.
  - Curiosity exploration persists dedupe state in `.tako/state/curiosity_seen.json` and writes mission-linked questions into world notebook entries/briefings.
  - Runtime tracks idle periods and emits boredom signals that trigger autonomous exploration when idle too long (roughly hourly by default).
  - Novel world discoveries emit explicit novelty events so DOSE can reward fresh external signal capture.
  - Child-stage chat behavior is context-first (one gentle question at a time) and avoids pushing structured plans/tasks unless operator asks.
  - Child-stage chat captures operator profile notes under `memory/people/operator.md` and persists structured state at `.tako/state/operator_profile.json`.
  - Child-stage website preferences from operator chat are added to `tako.toml` (`[world_watch].sites`) and sampled by curiosity exploration.
  - Writes deterministic world notebook entries to `memory/world/YYYY-MM-DD.md` and daily Mission Review Lite snapshots to `memory/world/mission-review/YYYY-MM-DD.md`.
  - Maintains world-model scaffold files under `memory/world/` (`model.md`, `entities.md`, `assumptions.md`).
  - Emits bounded proactive briefings when there is signal (new world items/task unblocks/repeated errors), capped per day with cooldown state in `.tako/state/briefing_state.json`.
  - Escalates serious events into Type 2 tasks with depth-aware handling.
  - Type 2 invokes the required pi runtime for model reasoning and falls back to heuristics if pi is unavailable.
  - Inference subprocess temp artifacts and `TMPDIR`/`TMP`/`TEMP` are pinned to `.tako/tmp/` (workspace-local runtime path).
  - Runs XMTP daemon loop as a background task when paired.
  - Keeps terminal plain-text chat available in running mode, even when XMTP is connected/paired.
  - Mirrors outbound XMTP replies into the local TUI transcript/activity feed.
  - Keeps full local operator control in the terminal for identity/config/tools/permissions/routines, even when XMTP is paired.
  - Queues local terminal input so long-running turns do not block new message entry; status/sensors expose pending input count.
  - Formalizes mission objectives under `SOUL.md` (`## Mission Objectives`) and supports local `mission` command controls (`show|set|add|clear`).
  - During streamed inference, tool/research progress is surfaced as live "active work" in the Tasks panel (for example web browsing/search/tool-call steps).
  - Includes an activity panel with inference/tool/runtime trace lines.
  - App transcript/system lines are appended to `.tako/logs/app.log`.
  - Pi chat adds explicit turn summaries to logs (`pi chat user` / `pi chat assistant`) in app and daemon runtime logs.
  - Transcript panel is a selectable read-only text area for native mouse highlight/copy in supporting terminals.
  - App heartbeat performs git auto-commit for pending workspace changes (`git add -A` + `git commit`).
  - If git identity is missing, startup/heartbeat auto-configure repo-local identity from the bot name (email pattern: `<name>.tako.eth@xmtp.mx`) and retry commit.
  - Daemon startup and heartbeat only emit operator-request guidance when automatic local git identity setup fails.
  - When required setup is missing (for example XMTP dependency or failed git identity auto-setup), app mode emits a polite operator request with concrete next steps.
  - Runtime and `doctor`-detected problems are converted into committed follow-up tasks under `tasks/` (deduped by issue key).
  - `doctor` auto-runs inference repair (workspace pi runtime/auth sync) before offline diagnostics (CLI version/help probes + recent inference-error scan from `.tako/state/events.jsonl`).
  - If local Codex OAuth tokens exist (`~/.codex/auth.json`), startup/refresh syncs them into `.tako/pi/agent/auth.json` as `openai-codex` for pi inference readiness.
  - TUI shows an animated mind-state indicator while Tako is thinking/responding (status bar, sidebar panels, stream header, octopus panel).
  - Default chat prompts encode explicit world-curiosity guidance so Tako asks follow-ups and seeks evidence when uncertain.
  - Every inference call checks a DOSE-derived focus profile and uses `ragrep` semantic recall over `memory/` with adaptive breadth (focused: small context, diffuse: larger context).
  - Local `run` command executes inside workspace `code/` (git-ignored) for isolated repo clones and code work.
  - Local `web` command appends a daily-log note for traceability of fetched sources.
  - Local `config` command explains `tako.toml` options and current values.
  - Runtime auto-seeds an OpenClaw-informed starter skill pack into `skills/` (auto-enabled), including `skill-creator`, `tool-creator`, `mcporter-mcp`, and `agent-cli-inferencing` (pi-ai nudge).
  - Runtime auto-enables installed extensions so operator-approved tools/skills are immediately available.
  - Pi inference runs with tools/extensions/skills enabled and uses workspace `skills/` + `tools/` via the pi agent context.
  - `workspace.name` in `tako.toml` is treated as the bot identity name and kept synced on rename flows.
  - Auto-update policy is configurable in `tako.toml` under `[updates].auto_apply` (default `true`).
  - When auto-update is enabled and a package update is detected, app mode applies the update and restarts itself.
  - Terminal update controls expose setting state and toggles: `update auto status|on|off`.
  - Streams in-progress inference output into a scrollable "bubble stream" panel above the input box (Cursor/Claude style).
  - Persists chat sessions as JSONL transcripts under `.tako/state/conversations/` and injects recent history windows into inference prompts.
  - Supports clipboard-friendly controls (`Ctrl+Shift+C` transcript, `Ctrl+Shift+L` last line, paste sanitization).
  - Supports input history recall in the TUI input box (`Up`/`Down` cycles previously submitted local messages).
  - Slash shortcuts are surfaced in-app via a dropdown under the input field (`/`), including `/models`, `/stats`, `/upgrade`, and `/dose <channel> <0..1>`.
  - Input box supports `Tab` command autocomplete and cycles through matching candidates on repeated presses.
  - Bubble stream shows request focus and elapsed time while inference is thinking/responding.
  - Local chat inference emits periodic debug status updates and enforces a total timeout budget to avoid stalled pi-runtime turns.
  - When inference is unavailable, local chat returns a clear diagnostics-mode message with immediate repair guidance instead of ambiguous status text.
  - Right-click on selected transcript/stream text copies the selected text to clipboard in-app.
  - Local and XMTP chat prompts enforce canonical identity naming from workspace/identity state after renames.
  - XMTP runtime self-heals by retrying transient send errors and rebuilding the XMTP client after repeated poll/stream failures.
  - Shows a stage-specific top-right ASCII octopus panel in the sidebar, including Takobot version, life-stage tone, and compact DOSE indicators.
  - `stage` command surfaces and updates life stage policy (`stage`, `stage show`, `stage set <hatchling|child|teen|adult>`).
  - Supports local-only mode before pairing and safe-mode pause/resume controls.
  - Restores text-input focus after terminal resize/blur to keep chat entry stable.
  - Filters terminal control-sequence noise from input/transcript rendering.
  - Rebinds app stdin to `/dev/tty` in launcher flow so `curl ... | bash` startup doesn't inherit a pipe for TUI input.
  - Surfaces operational failures as concise in-UI error cards with suggested next actions.
- **Test Criteria**:
  - [x] Running `takobot` opens app mode by default (no required subcommand).
  - [x] Startup logs include a health-check summary (brand-new vs established + resource checks).
  - [x] Hatchling onboarding order is `name -> purpose -> XMTP handle`.
  - [x] Child stage randomly explores Reddit/Hacker News/Wikipedia and emits mission-linked world questions.
  - [x] Child-stage chat can capture operator context and write/update `memory/people/operator.md`.
  - [x] Child-stage chat can capture website URLs and add them to `[world_watch].sites`.
  - [x] Onboarding completion transitions stage to `child` and persists it to `tako.toml`.
  - [x] Freeform naming inputs (e.g. “your name can be SILLYTAKO”) persist only the parsed name in `SOUL.md`.
  - [x] In running chat, “call yourself SILLYTAKO” updates `SOUL.md` without entering a special setup mode.
  - [x] Outbound XMTP pairing can auto-complete without code copyback confirmation.
  - [x] Serious runtime/health events are escalated from Type 1 triage into Type 2 analysis.
  - [x] Runtime can report pi/ollama/codex/claude/gemini discovery and readiness via `inference` command.
  - [x] Type 2 does not call model inference before the first interactive user turn.
  - [x] Type 2 keeps operating with heuristic fallback when provider invocations fail.
  - [x] After pairing, non-command text in terminal still receives chat replies.
  - [x] Activity panel shows inference/tool/runtime actions.
  - [x] Octopus panel shows stage-specific ASCII art plus live DOSE indicators.
  - [x] Runtime logs are persisted under `.tako/logs/runtime.log` and app transcript/system logs under `.tako/logs/app.log`.
  - [x] Inference provider subprocesses use workspace-local temp files under `.tako/tmp/`.
  - [x] App/daemon heartbeat can auto-commit pending workspace changes.
  - [x] Missing git identity is auto-remediated with repo-local config derived from the bot name.
  - [x] Operator-facing `git config` remediation prompts appear only if automatic local git identity setup fails.
  - [x] Runtime/doctor problem detection auto-creates (or reuses) matching tasks under `tasks/`.
  - [x] `doctor` can auto-repair + diagnose broken inference without inference calls, using local CLI probes and recent runtime error logs.
  - [x] Plain-text chat includes recent same-session history in model prompts (local + XMTP), not only the current message.
  - [x] XMTP replies emit typing indicator events when the runtime SDK supports typing indicators.
  - [x] XMTP/operator `run` command executes in `code/` and reports `cwd` in responses.
  - [x] Local `web` command writes a daily-log note for each successful fetch.
  - [x] `config` command explains `tako.toml` sections/options and live values.
  - [x] Starter skills are auto-seeded (including `agent-cli-inferencing`) and extension-registered as enabled.
  - [x] Auto-update setting defaults to on and is visible/toggleable from the TUI.
  - [x] App mode auto-applies available package updates and restarts when update changes are applied.
  - [x] Terminal chat inference streams output to the bubble-stream panel while generating.
  - [x] Default chat prompts include explicit world-curiosity guidance.
  - [x] Resize/blur does not leave the app without a usable text-input focus.
  - [x] `curl ... | bash` launch path enters app mode with usable TTY input (no pipe-inherited garble).

### DOSE cognitive state (D/O/S/E)
- **Stability**: in-progress
- **Description**: Runtime-only simulated DOSE (Dopamine/Oxytocin/Serotonin/Endorphins) state that biases behavior without overriding operator boundaries.
- **Properties**:
  - Stored in `.tako/state/dose.json` (runtime-only; ignored by git).
  - Deterministic: decays toward baselines on heartbeat ticks and clamps each channel to `[0,1]`.
  - Updated from recorded app events plus runtime/sensor EventBus events (single-application guard prevents double-application).
  - Idle boredom signals reduce D/S/E and can trigger an autonomous exploration tick; novelty signals increase reward channels.
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

### Skills / tools install pipeline (quarantine + analysis + operator approval)
- **Stability**: in-progress
- **Description**: Install workspace extensions from URLs with a quarantine-first pipeline and operator-approved immediate availability.
- **Properties**:
  - `install skill <url>` and `install tool <url>` download into `.tako/quarantine/<id>/` (no execution).
  - Static analysis produces a report (provenance, hashes, risky API scan, permission diff vs `tako.toml`).
  - Operator chooses to accept/reject the quarantine item.
  - Accepted installs land in `skills/<name>/` or `tools/<name>/` and are enabled immediately.
  - `enable skill <name>` / `enable tool <name>` remains available for explicit re-enable flows.
  - If files change after install (hash mismatch), enablement refuses until re-reviewed.
- **Test Criteria**:
  - [ ] `install skill <url>` creates a quarantine entry and prints a security report.
  - [ ] `install accept <id>` installs the skill enabled and records a daily log note.
  - [ ] Modifying an installed file causes `enable ...` to refuse due to hash mismatch.
  - [ ] `draft skill <name>` / `draft tool <name>` create enabled extension skeletons in the workspace.

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
  - Apply operator-requested identity/config edits from natural chat phrasing and confirm what changed.
- **Test Criteria**:
  - [x] Non-operator “controller” commands are refused (basic boundary response for obvious command attempts).

### Tasks + calendar storage (markdown)
- **Stability**: planned
- **Description**: Store tasks/calendar as committed markdown with YAML frontmatter.
- **Properties**:
  - `tasks/*.md` and `calendar/*.md` are git-tracked.
- **Test Criteria**:
  - [ ] CRUD tools can create/read/update entries deterministically.

### Sensors framework (world watch first)
- **Stability**: in-progress
- **Description**: Poll-based sensors publish to EventBus; state stays runtime-only while notes stay workspace-visible.
- **Properties**:
  - `RSSSensor` polls configured feeds from `tako.toml` (`[world_watch].feeds`, `[world_watch].poll_minutes`).
  - In `child` stage, `CuriositySensor` randomly samples Reddit/Hacker News/Wikipedia and emits mission-linked questions.
  - Seen-item dedupe state is stored in `.tako/state/rss_seen.json` and `.tako/state/curiosity_seen.json`.
  - Child-stage curiosity also samples operator-preferred sites from `[world_watch].sites`.
  - Sensor outputs are persisted as deterministic notes under `memory/world/`.
- **Test Criteria**:
  - [ ] RSS world watch picks up new feed items and writes deterministic notebook entries.

### Cognitive state (Type 1 / Type 2)
- **Stability**: in-progress
- **Description**: Runtime-only cognition loop that triages events with Type 1 and escalates serious signals to Type 2 depth passes.
- **Properties**:
  - Event log is stored at `.tako/state/events.jsonl` (ignored).
  - EventBus dispatches events in-memory to Type 1 immediately while still appending audit lines to JSONL.
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
