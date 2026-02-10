# Tako — Features

## Features

### Docs-first repo contract
- **Stability**: stable
- **Description**: The repo documents identity, invariants, onboarding, and durable memory as first-class artifacts.
- **Properties**:
  - Root docs exist: `AGENTS.md`, `SOUL.md`, `VISION.md`, `MEMORY.md`, `ONBOARDING.md`.
  - Feature state is tracked in `FEATURES.md`.
  - Website copy lives in `index.html`.
- **Test Criteria**:
  - [x] Root contract docs exist and are coherent.

### One-command runner (`tako.sh`)
- **Stability**: stable
- **Description**: Bootstraps a local Python environment and runs the Tako CLI.
- **Properties**:
  - Creates a virtualenv at `.venv/` if missing.
  - Installs dependencies from `requirements.txt` when needed.
  - Installs `xmtp` from PyPI when available; otherwise clones `xmtp-py` into `.tako/xmtp-py` and installs from source.
  - Supports legacy usage (`./tako.sh <to> [message]`) and explicit subcommands (`hi`, `run`, `doctor`).
- **Test Criteria**:
  - [x] `./tako.sh <to>` maps to `tako hi --to <to>`.
  - [x] `./tako.sh hi <to> [message]` works.
  - [x] `./tako.sh doctor` runs without requiring a recipient.

### CLI entrypoints (`tako`, `python -m tako_bot`, `tako.py`)
- **Stability**: in-progress
- **Description**: A multi-command CLI that keeps the legacy “send one DM” behavior while adding a daemon scaffold.
- **Properties**:
  - `tako hi --to <addr|ens> [--message ...]`
  - `tako run --operator <addr|ens>` (first run) and `tako run` (subsequent runs)
  - `tako doctor`
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
  - `XMTP_WALLET_KEY` and `XMTP_DB_ENCRYPTION_KEY` override generated values.
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
  - `--env` overrides `XMTP_ENV` (default: `production`).
- **Test Criteria**:
  - [x] Without `--message`, a default “hi from <hostname> (tako)” message is used.

### Local XMTP DB storage + reset
- **Stability**: stable
- **Description**: Stores XMTP state locally and supports a “nuke and rebuild” reset.
- **Properties**:
  - DB files live under `.tako/xmtp-db/` and are named `xmtp-{env}-{inbox_id}.db3`.
  - `TAKO_RESET_DB=1` deletes existing DB contents before starting.
- **Test Criteria**:
  - [x] `.tako/xmtp-db/` is created automatically if missing.

### Endpoint overrides + sync toggles
- **Stability**: stable
- **Description**: Supports endpoint overrides and toggling history/device sync behavior.
- **Properties**:
  - `XMTP_API_URL`, `XMTP_HISTORY_SYNC_URL`, and `XMTP_GATEWAY_HOST` override defaults.
  - History sync can be disabled via `XMTP_DISABLE_HISTORY_SYNC=1` or `XMTP_HISTORY_SYNC_URL=off`.
  - Device sync is disabled by default; enable via `TAKO_ENABLE_DEVICE_SYNC=1` (or disable explicitly via `XMTP_DISABLE_DEVICE_SYNC=1`).
- **Test Criteria**:
  - [x] History sync can be disabled via `XMTP_DISABLE_HISTORY_SYNC` or `XMTP_HISTORY_SYNC_URL=off`.

### Operator imprint (`.tako/operator.json`)
- **Stability**: in-progress
- **Description**: Tako stores a single operator (controller) and refuses silent reassignment.
- **Properties**:
  - On first `tako run --operator ...`, stores operator metadata under `.tako/operator.json`.
  - On subsequent runs, refuses operator changes without an explicit re-imprint flow.
- **Test Criteria**:
  - [x] First run requires `--operator`.
  - [x] If operator is already imprinted, mismatched `--operator` fails.

### Daily logs (`daily/YYYY-MM-DD.md`)
- **Stability**: in-progress
- **Description**: OpenClaw-style daily logs are committed under `daily/`, while runtime state stays under `.tako/`.
- **Properties**:
  - `tako run` ensures today’s daily log exists.
  - Daily log templates warn against secrets.
- **Test Criteria**:
  - [x] Running `tako run` creates `daily/YYYY-MM-DD.md` if missing.

### Tool discovery (`tools/*/tool.py`)
- **Stability**: in-progress
- **Description**: Tools live under `tools/` and are discoverable via a loader.
- **Properties**:
  - Loader scans for `tools/<name>/tool.py` exporting `TOOL_MANIFEST`.
  - Tool manifests declare permissions.
- **Test Criteria**:
  - [x] Loader can discover at least one tool (`tools/memory_append/tool.py`).

### Multi-instance lock
- **Stability**: planned
- **Description**: Prevent multiple `tako run` processes from using the same `.tako/` directory.
- **Properties**:
  - Uses a lock under `.tako/locks/`.
- **Test Criteria**:
  - [ ] Second instance fails fast with a clear error.

### Operator-only command authorization
- **Stability**: planned
- **Description**: Enforce that only the operator can modify identity/config/tools/routines.
- **Properties**:
  - Reject non-operator attempts to steer identity/config with a firm boundary.
- **Test Criteria**:
  - [ ] Non-operator “controller” commands are refused.

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
- **Description**: Import OpenClaw-style layouts into the new contract (SOUL/MEMORY/daily/tools).
- **Properties**:
  - Produces an `IMPORT_REPORT.md`.
- **Test Criteria**:
  - [ ] Imports a sample layout without losing provenance.

