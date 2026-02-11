# tako-bot

Tako is a **highly autonomous, operator-imprinted agent** built in **Python** with a docs-first memory system and **Type 1 / Type 2** thinking. The direction is informed by modern productivity research and stays web3-native via **XMTP** and **Ethereum** (with **Farcaster** support planned). Today, this repo includes:

- An always-on daemon that pairs an operator in-chat over XMTP
- A small command router over the operator channel (`help`, `status`, `doctor`, …)
- Docs-first repo contract (`SOUL.md`, `VISION.md`, `memory/MEMORY.md`, `ONBOARDING.md`)

## Docs

- Website: https://tako.bot (or `index.html` in this repo)
- Features: `FEATURES.md`
- Agent notes / lessons learned: `AGENTS.md`

## Quickstart

Bootstrap from your current directory (clone if needed), run first-wake onboarding, and start Tako:

```bash
curl -fsSL https://raw.githubusercontent.com/pierce403/tako-bot/main/setup.sh | bash
```

If you already have this repo cloned:

```bash
./start.sh
```

Pairing flow (XMTP operator channel is the only control plane):

- DM the printed `tako address` from the account you want as operator.
- Tako replies with a pairing challenge.
- Reply with `pair <code>` to imprint as the operator.
- After pairing, reply `help` for commands.

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
- Starts listening on XMTP and waits for the first inbound DM to initiate pairing.

## Configuration

There is **no user-facing configuration via environment variables or CLI flags**.

Any change that affects identity/config/tools/sensors/routines must be initiated by the operator over XMTP and (when appropriate) reflected by updating repo-tracked docs (`SOUL.md`, `memory/MEMORY.md`, etc).

## Developer utilities (optional)

- Local checks: `./tako.sh doctor`
- One-off DM send: `./tako.sh hi <xmtp_address_or_ens> ["message"]`

## Notes

- The bootstrap flow requires `uv` to manage the project virtualenv and Python dependencies.
- The XMTP Python SDK (`xmtp`) may compile native components on install, so make sure Rust is available if needed.
