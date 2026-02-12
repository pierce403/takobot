# tako-bot

Tako is a **highly autonomous, operator-imprinted agent** built in **Python** with a docs-first memory system and **Type 1 / Type 2** thinking. The direction is informed by modern productivity research and stays web3-native via **XMTP** and **Ethereum** (with **Farcaster** support planned). Today, this repo includes:

- A first-class interactive terminal app main loop (`tako`) with transcript, status bar, panels, and input box
- Startup health checks (instance shape, lock, resource probes) before entering the main loop
- Inference-provider discovery for Codex / Claude / Gemini CLIs with key-source detection
- Inference execution gate so first model call starts on the first interactive chat turn
- A background XMTP runtime with stream retries + polling fallback
- Event-log driven cognition: heartbeat + Type 1 triage + Type 2 escalation for serious signals
- XMTP control-channel handling with command router (`help`, `status`, `doctor`, `update`, `web`, `run`, `reimprint`) plus plain-text chat replies
- Built-in operator tools for webpage reads (`web <url>`) and local shell commands (`run <command>`)
- TUI activity feed (inference/tool/runtime events), clipboard copy actions, and a leveling ASCII octopus panel
- Docs-first repo contract (`SOUL.md`, `VISION.md`, `memory/MEMORY.md`, `ONBOARDING.md`)

## Docs

- Website: https://tako.bot (or `index.html` in this repo)
- Features: `FEATURES.md`
- Agent notes / lessons learned: `AGENTS.md`

## Quickstart

Bootstrap from your current directory (clone if needed), run first-wake onboarding, and start Tako:

```bash
curl -fsSL https://tako.bot/setup.sh | bash
```

If you already have this repo cloned:

```bash
./start.sh
```

`setup.sh` creates or switches to a local branch named `local` that tracks `origin/main`, so local changes stay isolated while upstream updates remain pullable.

Pairing flow:

- `tako` always starts the interactive terminal app first.
- During onboarding, Tako asks for XMTP setup ASAP (in-chat):
  - yes: outbound DM pairing (`.eth` or `0x...`) and assumes the recipient is ready
  - no: continue onboarding locally and allow later pairing from terminal
- Identity/purpose/routine prompts are delayed until inference has actually run (or can be started manually with `setup`).
- Identity naming accepts freeform input and extracts a clean name (for example, “your name can be SILLYTAKO”).
- After pairing, XMTP becomes the primary control plane for identity/config/tools/routines (`help`, `status`, `doctor`, `update`, `web`, `run`, `reimprint`).

## Architecture (minimal)

Committed (git-tracked):

- `SOUL.md`, `VISION.md`, `memory/MEMORY.md`, `ONBOARDING.md`, `AGENTS.md`
- `FEATURES.md` (feature tracker)
- `memory/dailies/YYYY-MM-DD.md` (daily logs)
- `memory/people/`, `memory/places/`, `memory/things/` (world notes)
- `tools/` (tool implementations)

Runtime-only (ignored):

- `.tako/keys.json` (XMTP wallet key + DB encryption key; unencrypted, file perms only)
- `.tako/operator.json` (operator imprint metadata)
- `.tako/xmtp-db/` (local XMTP DB)
- `.tako/state/**` (runtime state: heartbeat/cognition/etc)
- `.venv/` (uv-managed virtualenv)

## What happens on first run

- Creates a local Python virtual environment in `.venv/` using `uv`.
- Installs dependencies from `requirements.txt` via `uv pip`.
- Installs the XMTP Python SDK (`xmtp`) via `uv pip`. If it is not yet on PyPI, it clones `xmtp-py` and installs from source.
- Generates a local key file at `.tako/keys.json` with a wallet key and DB encryption key (unencrypted; protected by file permissions).
- Creates a local XMTP database at `.tako/xmtp-db/`.
- Launches the interactive terminal app main loop (`tako app`, default `tako`).
- Runs a startup health check to classify instance context (brand-new vs established), verify lock/safety, and inspect local resources.
- Detects available inference CLIs (`codex`, `claude`, `gemini`) and key/auth sources, then persists runtime metadata to `.tako/state/inference.json`.
- Runs onboarding as an explicit state machine inside the app, starting with XMTP channel setup.
- Shows an activity panel in the TUI so you can see inference/tool/runtime actions as they happen.
- Starts heartbeat + event-log ingestion and continuously applies Type 1 triage; serious events trigger Type 2 tasks with depth-based handling.
- Type 2 escalation uses discovered inference providers with fallback across ready CLIs after the first interactive chat turn, then falls back to heuristic guidance if inference calls fail.
- If paired, starts background XMTP runtime and keeps terminal as local cockpit with plain-text chat still available.

## Configuration

There is **no user-facing configuration via environment variables or CLI flags**.

Any change that affects identity/config/tools/sensors/routines must be initiated by the operator over XMTP and (when appropriate) reflected by updating repo-tracked docs (`SOUL.md`, `memory/MEMORY.md`, etc).

## Developer utilities (optional)

- Local checks: `./tako.sh doctor`
- One-off DM send: `./tako.sh hi <xmtp_address_or_ens> ["message"]`
- Direct daemon (dev): `./tako.sh run`

## Notes

- The terminal app flow requires `uv` to manage the project virtualenv and Python dependencies.
- `setup.sh` / `start.sh` will attempt a repo-local `uv` install automatically at `.tako/bin/uv` if `uv` is missing.
- `start.sh` now delegates onboarding to the in-app terminal UX; it no longer runs shell prompts for identity setup.
- The daemon now retries XMTP stream subscriptions with backoff when transient group/identity stream errors occur.
- When stream instability persists, the daemon falls back to polling message history and retries stream mode after polling stabilizes.
- XMTP client initialization disables history sync by default for compatibility.
- Runtime event log lives at `.tako/state/events.jsonl` and is consumed by the Type 1/Type 2 cognition pipeline.
- Runtime inference metadata lives at `.tako/state/inference.json` (no raw secrets written by Tako).
- App launcher (`tako.sh`) rebinds stdin to `/dev/tty` for app mode, so `curl ... | bash` startup can still run interactive TUI input correctly.
- The XMTP Python SDK (`xmtp`) may compile native components on install, so make sure Rust is available if needed.
