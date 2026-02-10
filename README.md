# tako-bot

Tako is an **XMTP-native, operator-imprinted agent**. Today, this repo includes:

- A one-off “hi” sender (address or ENS)
- A `run` daemon scaffold (heartbeat + operator control plane)
- Docs-first repo contract (`SOUL.md`, `VISION.md`, `MEMORY.md`, `ONBOARDING.md`)

## Docs

- Website: https://tako.bot (or `index.html` in this repo)
- Features: `FEATURES.md`
- Agent notes / lessons learned: `AGENTS.md`

## Quickstart

One-off DM:

```bash
./tako.sh hi deanpierce.eth
```

You can optionally pass a custom message as the second argument:

```bash
./tako.sh hi deanpierce.eth "hi from the backup server"
```

Daemon scaffold (operator imprint on first run):

```bash
./tako.sh run --operator deanpierce.eth
```

Tako will DM the operator on startup; reply `help` for the current command set.

Environment checks:

```bash
./tako.sh doctor
```

Backwards compatible legacy form (maps to `tako hi`):

```bash
./tako.sh deanpierce.eth "optional message"
```

## Architecture (minimal)

Committed (git-tracked):

- `SOUL.md`, `VISION.md`, `MEMORY.md`, `ONBOARDING.md`, `AGENTS.md`
- `FEATURES.md` (feature tracker)
- `daily/YYYY-MM-DD.md` (daily logs)
- `tools/` (tool implementations)

Runtime-only (ignored):

- `.tako/keys.json` (XMTP wallet key + DB encryption key; unencrypted, file perms only)
- `.tako/operator.json` (operator imprint metadata)
- `.tako/xmtp-db/` (local XMTP DB)
- `.tako/state/**` (runtime state: heartbeat/cognition/etc)
- `.venv/` (virtualenv)

## What happens on first run

- Creates a local Python virtual environment in `.venv/`.
- Installs dependencies from `requirements.txt`.
- Installs the XMTP Python SDK (`xmtp`). If it is not yet on PyPI, it clones `xmtp-py` and installs from source.
- Generates a local key file at `.tako/keys.json` with a wallet key and DB encryption key (unencrypted; protected by file permissions).
- Creates a local XMTP database at `.tako/xmtp-db/`.

## Configuration

Environment variables:

- `XMTP_ENV`: Set the XMTP environment (defaults to `production`).
- `XMTP_API_URL`, `XMTP_HISTORY_SYNC_URL`, `XMTP_GATEWAY_HOST`: Override XMTP endpoints.
- `XMTP_DISABLE_HISTORY_SYNC=1`: Disable history sync (uses primary API for identity calls).
- `XMTP_DISABLE_DEVICE_SYNC=1`: Disable the device sync worker (default is disabled).
- `TAKO_ENABLE_DEVICE_SYNC=1`: Force-enable device sync if you want it.
- `TAKO_RESET_DB=1`: Delete the local XMTP database before starting (useful if the DB is corrupted or encrypted with a different key).
- `TAKO_ENS_RPC_URL`: Ethereum RPC endpoint used for ENS name resolution (defaults to `https://ethereum.publicnode.com`).
- `TAKO_ENS_RPC_URLS`: Comma-separated list of RPC endpoints to try in order for ENS resolution.
- `XMTP_WALLET_KEY` and `XMTP_DB_ENCRYPTION_KEY`: Override the generated keys if you manage them externally.

## Notes

- The XMTP Python SDK (`xmtp`) may compile native components on install, so make sure Rust is available if needed.
