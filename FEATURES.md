# Tako — Features

## Features

### Docs-first repo contract
- **Stability**: stable
- **Description**: The repo documents identity, invariants, onboarding, and durable memory as first-class artifacts.
- **Properties**:
  - Root docs exist: `AGENTS.md`, `SOUL.md`, `VISION.md`, `ONBOARDING.md`.
  - Memory docs live under `memory/` with canonical `memory/MEMORY.md`.
  - Feature state is tracked in `FEATURES.md`.
  - Website copy lives in `index.html`.
- **Test Criteria**:
  - [x] Root contract docs exist and are coherent.

### One-command runner (`tako.sh`)
- **Stability**: stable
- **Description**: Bootstraps a local Python environment and starts the daemon.
- **Properties**:
  - Uses `uv` to create/manage a virtualenv at `.venv/`.
  - Installs dependencies from `requirements.txt` via `uv pip` when needed.
  - Installs `xmtp` via `uv pip` from PyPI when available; otherwise clones `xmtp-py` into `.tako/xmtp-py` and installs from source.
  - Defaults to `tako run` when invoked with no arguments.
  - Supports `start` as an alias for `run`.
  - Exposes developer utilities (`doctor`, `hi`) for debugging/backwards compatibility.
- **Test Criteria**:
  - [x] `./tako.sh` starts the daemon.
  - [x] `./tako.sh start` starts the daemon.
  - [x] `./tako.sh doctor` runs without requiring a recipient.

### Setup + start bootstrap (`setup.sh`, `start.sh`)
- **Stability**: in-progress
- **Description**: First-wake bootstrap from current directory, then onboarding prompts and daemon start.
- **Properties**:
  - `setup.sh` bootstraps (or reuses) the repo in the caller's current directory, then runs `start.sh`.
  - `setup.sh` ensures a local working branch (`local`) tracks `origin/main` for local-first changes with upstream sync.
  - `start.sh` checks repo layout/home sanity, prompts for SOUL identity fields, then runs `tako.sh`.
  - If installed, `start.sh` can optionally call one-shot local inference CLIs (`codex`, `claude`, `gemini`) to suggest SOUL defaults.
  - If one-shot inference fails, `start.sh` prints attempted command diagnostics (exit + stderr summary) before manual fallback.
  - If `uv` is missing, `start.sh` attempts a repo-local install at `.tako/bin/uv` before handing off to `tako.sh`.
  - Site and README expose a `curl -fsSL https://tako.bot/setup.sh | bash` path.
- **Test Criteria**:
  - [x] `./setup.sh` targets current directory semantics (not hardcoded `$HOME`).
  - [x] `./setup.sh` creates/switches to a local branch (`local`) that tracks `origin/main`.
  - [x] `./start.sh` exists and launches Tako through `tako.sh`.

### CLI entrypoints (`tako`, `python -m tako_bot`, `tako.py`)
- **Stability**: in-progress
- **Description**: A multi-command CLI where `run` starts the daemon; operator management happens over XMTP.
- **Properties**:
  - `tako run` starts the daemon, prints `tako address`, and listens for pairing DMs.
  - `tako run` automatically retries XMTP message stream subscriptions with backoff on transient stream failures.
  - Pairing and all post-boot management happens over XMTP (not CLI flags).
  - `tako doctor` and `tako hi` exist as developer utilities.
  - `tako.py` remains as a backwards-compatible wrapper.
- **Test Criteria**:
  - [x] `python -m tako_bot doctor` runs and reports missing dependencies clearly.
  - [x] `python tako.py --to <addr>` invokes the `hi` command path.

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

### One-off XMTP DM send (`tako hi`)
- **Stability**: stable
- **Description**: Creates an XMTP client, opens a DM, and sends a message.
- **Properties**:
  - Default message includes the machine hostname.
  - `--message` overrides the default message.
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
  - On first inbound DM, Tako issues a pairing challenge; first successful `pair <code>` becomes the operator imprint.
  - Stores `operator_inbox_id` under `.tako/operator.json` (runtime-only; ignored by git).
  - Re-imprinting requires an explicit operator command over XMTP (`reimprint CONFIRM`).
- **Test Criteria**:
  - [x] `tako run` starts unpaired and waits for inbound DMs to begin pairing.
  - [x] Once paired, only the operator inbox can run `status` / `doctor`.

### Daily logs (`memory/dailies/YYYY-MM-DD.md`)
- **Stability**: in-progress
- **Description**: OpenClaw-style daily logs are committed under `memory/dailies/`, while runtime state stays under `.tako/`.
- **Properties**:
  - `tako run` ensures today’s daily log exists.
  - Daily log templates warn against secrets.
- **Test Criteria**:
  - [x] Running `tako run` creates `memory/dailies/YYYY-MM-DD.md` if missing.

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
- **Description**: Prevent multiple `tako run` processes from using the same `.tako/` directory.
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
- **Stability**: planned
- **Description**: Runtime-only cognitive state that influences cadence and depth, never overriding SOUL/AGENTS constraints.
- **Properties**:
  - Stored in `.tako/state/cognition.json` (ignored).
- **Test Criteria**:
  - [ ] Operator can request a Type 2 pass for risky/config changes.

### “Eat the crab” importer
- **Stability**: planned
- **Description**: Import OpenClaw-style layouts into the new contract (SOUL/memory/tools).
- **Properties**:
  - Produces an `IMPORT_REPORT.md`.
- **Test Criteria**:
  - [ ] Imports a sample layout without losing provenance.
