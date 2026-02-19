# takobot

Tako is **your highly autonomous octopus friend** built in **Python** with a docs-first memory system and **Type 1 / Type 2** thinking. By default, Tako is intentionally curious about the world and pushes toward evidence-backed answers. The direction is informed by modern productivity research and stays web3-native via **XMTP** and **Ethereum** (with **Farcaster** support planned). Today, this repo includes:

- A first-class interactive terminal app main loop (`takobot`) with transcript, status bar, panels, and input box
- Installed shell wrapper support: `tako.sh` is packaged for deployments and fresh workspaces now materialize a local `tako.sh` launcher (dispatching to installed `takobot` outside repo mode)
- Startup health checks (instance shape, lock, resource probes) before entering the main loop
- Pi-first/required inference discovery: Takobot installs and uses workspace-local `pi` runtime (`@mariozechner/pi-ai` + `@mariozechner/pi-coding-agent`) and records key-source detection
- Pi auth bridging: when available, Takobot adopts local-system API keys (environment and common CLI auth files) for pi runtime usage
- Assisted pi login workflow: `inference login` can relay pi login prompts back to the operator (`inference login answer <text>`) and auto-syncs Codex OAuth from `~/.codex/auth.json` into `.tako/pi/agent/auth.json`
- Pi chat inference keeps tools/skills/extensions enabled and links workspace `skills/` + `tools/` into the pi agent runtime context
- Pi chat turn summaries are now written to logs (`.tako/logs/runtime.log` and `.tako/logs/app.log`) so operator prompts/replies are traceable during long runs
- Inference command-level failures now log invoked command + output tails to `.tako/logs/error.log`
- Default pi tooling install in workspace (`.tako/pi/node`), with local `nvm` bootstrap under `.tako/nvm` when host Node/npm are missing or Node is incompatible (`<20`)
- Inference execution gate so first model call starts on the first interactive chat turn
- OpenClaw-style conversation management: per-session JSONL transcripts under `.tako/state/conversations/` with bounded history windows injected into prompts
- A background XMTP runtime with stream retries + polling fallback
- XMTP profile sync: Takobot best-effort syncs XMTP display name from identity, generates a deterministic avatar at `.tako/state/xmtp-avatar.svg`, and records sync state in `.tako/state/xmtp-profile.json`
- EventBus-driven cognition: in-memory event fanout + JSONL audit + Type 1 triage + Type 2 escalation
- World Watch sensor loop: RSS/Atom polling plus child-stage curiosity crawling (Reddit/Hacker News/Wikipedia), deterministic world notebook writes, and bounded briefings
- Boredom/autonomy loop: when runtime stays idle, DOSE indicators drift down and Tako triggers boredom-driven exploration (about hourly by default) to find novel signals
- Child-stage chat tone is relationship-first: it asks one small context question at a time (who/where/what the operator does) and avoids forcing task frameworks unless asked
- Child-stage chat avoids interrogation loops: answers first, avoids asking which channel is in use, and uses profile-aware anti-repeat guidance so follow-up questions feel natural
- Child-stage operator context is captured into `memory/people/operator.md`; shared websites are added to `[world_watch].sites` in `tako.toml` for monitoring
- Heartbeat-time git hygiene: if workspace changes are pending, Tako stages (`git add -A`) and commits automatically, and verifies the repo is clean after commit
- Missing-setup prompts: when required config/deps are missing and auto-remediation fails, Tako asks the operator with concrete fix steps
- Runtime problem capture: detected warnings/errors are converted into committed `tasks/` items for follow-up
- Animated "mind" indicator in the TUI (status/sidebar/stream/octopus panel) while Tako is thinking or responding
- Auto-update setting (`tako.toml` → `[updates].auto_apply = true` by default) with in-app apply + self-restart when a new package release is detected
- XMTP control-channel handling with command router (`help`, `status`, `doctor`, `config`, `jobs`, `task`, `tasks`, `done`, `morning`, `outcomes`, `compress`, `weekly`, `promote`, `update`, `web`, `run`, `reimprint`) plus plain-text chat replies
- Natural-language scheduling for recurring jobs (`every day at 3pm ...`) with persisted job state at `.tako/state/cron/jobs.json`
- Built-in operator tools for webpage reads (`web <url>`) and local shell commands (`run <command>`), plus standard autonomous web tools in `tools/`: `web_search` and `web_fetch`
- Code work isolation: shell command execution runs in `code/` (git-ignored) so repo clones and code sandboxes stay out of workspace history
- Built-in starter skills are auto-seeded into `skills/` and auto-enabled: OpenClaw top skills, `skill-creator`, `tool-creator`, MCP-focused `mcporter-mcp`, and an `agent-cli-inferencing` guide that nudges toward `@mariozechner/pi-ai`
- TUI activity feed (inference/tool/runtime events), clipboard copy actions, and a stage-specific ASCII octopus panel with Takobot version + DOSE indicators
- Research visibility: during streamed inference, inferred tool steps (for example web browsing/search/tool calls) are surfaced as live "active work" in the Tasks panel
- TUI input history recall: press `↑` / `↓` in the input box to cycle previously submitted local messages
- Slash-command UX in the TUI: typing `/` opens a dropdown under the input field with command shortcuts; includes `/models` for pi/inference auth config, `/jobs` for schedule control, `/upgrade` as update alias, `/stats` for runtime counters, and `/dose ...` for direct DOSE level tuning
- TUI command entry supports `Tab` autocomplete for command names (with candidate cycling on repeated `Tab`)
- Local TUI input is now queued: long-running turns no longer block new message entry, and pending input count is shown in status/sensors
- XMTP outbound replies are mirrored into the local TUI transcript/activity feed so remote conversations stay visible in one place
- Mission objectives are formalized in `SOUL.md` (`## Mission Objectives`) and editable in-app via `mission` commands (`mission show|set|add|clear`)
- Runtime writes deterministic world notes under `memory/world/YYYY-MM-DD.md` and daily mission snapshots under `memory/world/mission-review/YYYY-MM-DD.md`
- Focus-aware memory recall on every inference: DOSE emotional state drives how much semantic RAG context is pulled from `memory/` via `ragrep` (minimal context when focused, broader context when diffuse)
- Prompt context stack parity across channels: local TUI chat and XMTP chat now both include `SOUL.md`/`SKILLS.md`/`TOOLS.md` excerpts, live skills/tools inventories, `MEMORY.md` frontmatter, focus summary, semantic RAG context, and recent conversation history
- Effective thinking defaults are split by cognition lane: Type1 uses fast `minimal` thinking, Type2 uses deep `xhigh` thinking
- Life-stage model (`hatchling`, `child`, `teen`, `adult`) persisted in `tako.toml` with stage policies for routines/cadence/budgets
- Bubble stream now shows the active request focus + elapsed time while thinking/responding so long responses stay transparent
- Incremental `pi thinking` stream chunks now render inline in one evolving status line (instead of newline-per-token); structural markers stay on separate lines
- Inference debug telemetry is now more verbose by default (ready-provider list, periodic waiting updates, app-log traces) with a bounded total local-chat timeout to avoid indefinite spinner stalls
- TUI right-click on selected transcript/stream text now triggers in-app copy-to-clipboard without clearing the selection
- XMTP daemon resilience: retries transient send failures and auto-rebuilds XMTP client sessions after repeated stream/poll failures
- Local/XMTP chat prompts now enforce canonical identity naming from workspace/identity state, so self-introductions stay consistent after renames
- Productivity engine v1: GTD + PARA folders (`tasks/`, `projects/`, `areas/`, `resources/`, `archives/`), daily outcomes, weekly review, progressive summaries
- Docs-first repo contract (`SOUL.md`, `VISION.md`, `MEMORY.md`, `SKILLS.md`, `TOOLS.md`, `ONBOARDING.md`)
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
- During hatchling onboarding, Tako asks in this order:
  - name
  - purpose
  - XMTP handle yes/no (pair now or continue local-only)
- Identity naming accepts freeform input and uses inference to extract a clean name (for example, “your name can be SILLYTAKO”).
- Rename handling in running chat is inference-classified (not phrase-gated): if you request a rename without giving the target name, Tako asks for the exact replacement.
- After pairing, XMTP adds remote operator control for identity/config/tools/routines (`help`, `status`, `doctor`, `config`, `jobs`, `task`, `tasks`, `done`, `morning`, `outcomes`, `compress`, `weekly`, `promote`, `update`, `web`, `run`, `reimprint`) while the terminal keeps full local operator control.

Productivity (GTD + PARA):

- `morning` sets today’s 3 outcomes (stored in `memory/dailies/YYYY-MM-DD.md`).
- `task <title>` creates a committed task file under `tasks/`.
- `tasks` lists open tasks (filters: `project`, `area`, `due`).
- `done <task-id>` completes a task.
- `compress` writes a progressive summary block into today’s daily log.
- `weekly` runs a weekly review report.
- `promote <note>` appends an operator-approved durable note into `MEMORY.md`.
- `jobs add <natural schedule>` (or plain language like `every day at 3pm explore ai news`) schedules recurring actions.

## Architecture (minimal)

Committed (git-tracked):

- `SOUL.md`, `MEMORY.md`, `SKILLS.md`, `TOOLS.md`, `ONBOARDING.md`, `AGENTS.md`, `tako.toml`
- `FEATURES.md` (feature tracker)
- `memory/dailies/YYYY-MM-DD.md` (daily logs)
- `memory/world/` (`YYYY-MM-DD.md`, `model.md`, `entities.md`, `assumptions.md`)
- `memory/reflections/`, `memory/contradictions/` (reflection + contradiction tracking)
- `tasks/`, `projects/`, `areas/`, `resources/`, `archives/` (execution structure)
- `tools/` (workspace tools; operator-approved installs are auto-enabled)
- `skills/` (workspace skills; starter pack + operator-approved installs are auto-enabled)

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
- Installs local pi runtime in `.tako/pi/node` (`@mariozechner/pi-ai` + `@mariozechner/pi-coding-agent`) by default; if Node/npm are missing or Node is below the pi requirement (`>=20`), bootstrap installs workspace-local `nvm` + Node under `.tako/nvm` first.
- Materializes the workspace from engine templates (`takobot/templates/**`) without overwriting existing files (including workspace `tako.sh` launcher materialization).
- Seeds a baseline model tuning guide at `resources/model-guide.md`.
- Initializes git (if available) and commits the initial workspace.
- If initial git commit is blocked by missing identity, bootstrap sets repo-local fallback identity from `workspace.name` (email format: `<name>.tako.eth@xmtp.mx`) and retries.
- Ensures a git-ignored `code/` directory exists for temporary repo clones/code work.
- Generates a local key file at `.tako/keys.json` with a wallet key and DB encryption key (unencrypted; protected by file permissions).
- Creates runtime logs/temp directories at `.tako/logs/` and `.tako/tmp/`.
- Creates a local XMTP database at `.tako/xmtp-db/`.
- Launches the interactive terminal app main loop (`takobot`, default).
- Runs a startup health check to classify instance context (brand-new vs established), verify lock/safety, and inspect local resources.
- If required setup is missing, emits an in-app operator request with direct remediation steps.
- Detects pi runtime/auth/key sources (including Codex OAuth import into `.tako/pi/agent/auth.json` when available) and persists runtime metadata to `.tako/state/inference.json`.
- If workspace-local pi runtime is missing, runtime discovery bootstraps workspace-local nvm/node and installs pi tooling under `.tako/`.
- Loads auto-update policy from `tako.toml` (`[updates].auto_apply`, default `true`).
- Runs stage-aware onboarding as an explicit state machine inside the app (`name -> purpose -> XMTP handle`).
- Shows an activity panel in the TUI so you can see inference/tool/runtime actions as they happen.
- Shows the top-right octopus panel with Takobot version and compact DOSE indicators (D/O/S/E).
- Starts the runtime service (heartbeat + exploration + sensors) and continuously applies Type 1 triage; serious events trigger Type 2 tasks with depth-based handling.
- Type 2 escalation uses the required pi runtime after the first interactive turn; if pi is unavailable/fails, Type 2 falls back to heuristic guidance.
- Seeds starter skills into `skills/`, registers them, and auto-enables installed extensions.
- If paired, starts background XMTP runtime and keeps terminal as local cockpit with plain-text chat still available.

## Configuration

There is **no user-facing configuration via environment variables or CLI flags**.

Workspace configuration lives in `tako.toml` (no secrets).
- `workspace.name` is the bot’s identity name and is kept in sync with rename/identity updates.
- Auto-update policy lives in `[updates]` (`auto_apply = true` by default). In the TUI: `update auto status|on|off`.
- World-watch feeds live in `[world_watch]` (`feeds = [...]`, `poll_minutes = <minutes>`).
- Website watch-list lives in `[world_watch].sites` and is automatically updated when child-stage chat captures operator-preferred websites.
- In `child` stage, world-watch also performs random curiosity sampling from Reddit, Hacker News, and Wikipedia.
- Use `config` (local TUI) or XMTP `config` to get a guided explanation of all `tako.toml` options and current values.
- Inference auth/provider settings are runtime-local in `.tako/state/inference-settings.json` and can be managed directly with `inference ...` commands (provider preference `auto|pi`, API keys, pi OAuth inventory).
- `doctor` runs local/offline inference diagnostics (CLI probes + recent inference error scan), attempts automatic workspace-local inference repair first, and does not depend on inference being available.
- Extension downloads are always HTTPS; non-HTTPS is not allowed.
- Security permission defaults for enabled extensions are now permissive by default (`network/shell/xmtp/filesystem = true`), and can be tightened in `tako.toml`.

Any change that affects identity/config/tools/sensors/routines must be initiated by the operator (terminal app or paired XMTP). Natural-language operator requests can be applied directly, and durable changes should still be reflected in repo-tracked docs (`SOUL.md`, `MEMORY.md`, etc).

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
- Runtime event log lives at `.tako/state/events.jsonl` as an audit stream; events are consumed in-memory via EventBus (no JSONL polling queue).
- World Watch sensor state is stored in `.tako/state/rss_seen.json` and `.tako/state/curiosity_seen.json`; briefing cadence/state is stored in `.tako/state/briefing_state.json`.
- Runtime inference metadata lives at `.tako/state/inference.json` (no raw secrets written by Tako).
- Runtime daemon logs are appended to `.tako/logs/runtime.log`; TUI transcript/system logs are appended to `.tako/logs/app.log`.
- Pi-backed chat adds explicit `pi chat user` / `pi chat assistant` summary lines in runtime/app logs.
- Inference now runs through workspace-local pi runtime; if pi is not available, Takobot falls back to non-inference heuristic responses.
- Inference subprocess temp output and `TMPDIR`/`TMP`/`TEMP` are pinned to `.tako/tmp/` (workspace-local only).
- Chat context is persisted in `.tako/state/conversations/` (`sessions.json` + per-session JSONL transcripts) and recent turns are injected into prompt context.
- On each heartbeat, Tako checks git status and auto-commits pending workspace changes (`git add -A` + `git commit`) when possible.
- Scheduled jobs are evaluated on heartbeat ticks (default cadence: every 30s in app mode), then queued as local actions when due.
- If git auto-commit encounters missing git identity, Tako auto-configures repo-local identity from the bot name (`<name> <name.tako.eth@xmtp.mx>`) and retries the commit.
- When runtime/doctor detects actionable problems (git/inference/dependency/runtime), Tako opens/maintains matching tasks under `tasks/` automatically.
- The bootstrap launcher rebinds stdin to `/dev/tty` for app mode, so `curl ... | bash` can still start an interactive TUI.
- XMTP replies now use a typing indicator when supported by the installed XMTP SDK/runtime.
- Transcript view is now selectable (read-only text area), so mouse highlight/copy works directly in compatible terminals.
- Input box supports shell-style history recall (`↑` / `↓`) for previously submitted local messages.
- Web reads are fetched with the built-in `web` tool and logged into the daily notes stream for traceability.
- Semantic memory recall uses `ragrep` when installed (`ragrep` CLI); index state is runtime-only at `.tako/state/ragrep-memory.db`.
- XMTP support is installed with `takobot` by default; if an existing environment is missing it, run `pip install --upgrade takobot xmtp` (native build tooling such as Rust may be required).
