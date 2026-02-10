# tako-bot — Features

## Features

### One-command runner (`tako.sh`)
- **Stability**: stable
- **Description**: Bootstraps a local Python environment and runs the XMTP “hi” client.
- **Properties**:
  - Creates a virtualenv at `.venv/` if missing.
  - Installs dependencies from `requirements.txt` when needed.
  - Installs `xmtp` from PyPI when available; otherwise clones `xmtp-py` into `.tako/xmtp-py` and installs from source.
- **Test Criteria**:
  - [x] `./tako.sh <to>` invokes `tako.py` with `--to <to>`.
  - [x] When `.venv/` is missing, it is created on first run.
  - [x] When `xmtp` is not importable, the script installs it (PyPI or source fallback).

### Local config + key management
- **Stability**: stable
- **Description**: Generates and stores keys locally, with env var overrides for managed deployments.
- **Properties**:
  - Creates `.tako/config.json` with `wallet_key` and `db_encryption_key` if missing.
  - Attempts to set config file permissions to `0600` (best-effort).
  - `XMTP_WALLET_KEY` and `XMTP_DB_ENCRYPTION_KEY` override generated values.
- **Test Criteria**:
  - [x] If `.tako/config.json` is missing, running `tako.py` creates it.
  - [x] If `XMTP_WALLET_KEY`/`XMTP_DB_ENCRYPTION_KEY` are set, they are used without requiring the config.

### Recipient resolution (address + ENS)
- **Stability**: stable
- **Description**: Accepts `0x…` addresses directly and resolves `.eth` names to addresses.
- **Properties**:
  - `0x…` recipients are treated as already-resolved addresses.
  - ENS resolution tries RPC endpoints in order: `--ens-rpc-url`, `TAKO_ENS_RPC_URLS`, `TAKO_ENS_RPC_URL`, defaults.
  - If RPC-based ENS resolution fails, it falls back to a public resolver.
- **Test Criteria**:
  - [x] A `0x…` recipient is returned unchanged.
  - [x] A `.eth` recipient attempts resolution via configured RPC endpoints.
  - [x] If RPC resolution fails, a fallback resolver is attempted before erroring.

### Send a DM via XMTP
- **Stability**: stable
- **Description**: Creates an XMTP client, opens a DM, and sends a message.
- **Properties**:
  - Default message includes the machine hostname.
  - `--message` overrides the default message.
  - `--env` overrides `XMTP_ENV` (default: `production`).
- **Test Criteria**:
  - [x] CLI requires `--to`.
  - [x] Without `--message`, a default “hi from <hostname> (tako)” message is used.
  - [x] With `--message`, the provided string is sent.

### Local XMTP DB storage + reset
- **Stability**: stable
- **Description**: Stores XMTP state locally and supports a “nuke and rebuild” reset.
- **Properties**:
  - DB files live under `.tako/xmtp-db/` and are named `xmtp-{env}-{inbox_id}.db3`.
  - `TAKO_RESET_DB=1` deletes existing DB contents before starting.
- **Test Criteria**:
  - [x] `.tako/xmtp-db/` is created automatically if missing.
  - [x] With `TAKO_RESET_DB=1`, existing DB files are removed before sending.

### Endpoint overrides + sync toggles
- **Stability**: stable
- **Description**: Supports endpoint overrides and toggling history/device sync behavior.
- **Properties**:
  - `XMTP_API_URL`, `XMTP_HISTORY_SYNC_URL`, and `XMTP_GATEWAY_HOST` override defaults.
  - History sync can be disabled via `XMTP_DISABLE_HISTORY_SYNC=1` or `XMTP_HISTORY_SYNC_URL=off`.
  - Device sync is disabled by default; enable via `TAKO_ENABLE_DEVICE_SYNC=1` (or disable explicitly via `XMTP_DISABLE_DEVICE_SYNC=1`).
- **Test Criteria**:
  - [x] Endpoint override env vars are passed into XMTP client options.
  - [x] History sync can be disabled via `XMTP_DISABLE_HISTORY_SYNC` or `XMTP_HISTORY_SYNC_URL=off`.
  - [x] Device sync defaults to disabled and can be toggled via env vars.

### Actionable error hints
- **Stability**: stable
- **Description**: Prints targeted hints for common networking and DB failure modes.
- **Properties**:
  - Adds a network hint for common Identity/API connectivity failures.
  - Adds a DB reset hint for likely corruption/encryption mismatches.
- **Test Criteria**:
  - [x] When an error matches a known failure pattern, a tip is printed to stderr.

### Dry-run mode (no send)
- **Stability**: planned
- **Description**: Resolve the recipient and print the final message/options without sending.
- **Properties**:
  - Prints resolved address, environment, and selected endpoints.
  - Exits with a non-zero status if recipient resolution fails.
- **Test Criteria**:
  - [ ] CLI supports `--dry-run` and produces no outbound XMTP send.

### Healthcheck mode
- **Stability**: planned
- **Description**: Validate basic prerequisites (network reachability, ENS resolution, DB access) without messaging anyone.
- **Properties**:
  - Reports failures with actionable next steps.
- **Test Criteria**:
  - [ ] CLI supports `--healthcheck` and exits non-zero on failed checks.

