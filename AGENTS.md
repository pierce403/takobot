# Agent Notes — tako-bot

This repo is a tiny XMTP client that lets a server send a friendly DM (“hi”) to an XMTP address or ENS name.

## Project Intent

- Keep the core “send one DM” flow minimal and reliable.
- Be easy to run on a fresh box (single `./tako.sh …` command).
- Prefer clear, actionable errors over clever abstractions.

## Do Not Commit

- `.tako/config.json` (contains a wallet private key + DB encryption key)
- `.tako/xmtp-db/` and any `*.db3*` files
- `.venv/`, caches, build outputs

## Entrypoints

- `./tako.sh <xmtp_address_or_ens> [message]` (bootstraps venv + deps)
- `python3 tako.py --to <xmtp_address_or_ens> [--message "..."]`

## Repo Map

- `tako.py`: config management, ENS resolution, XMTP send
- `tako.sh`: venv/bootstrap + optional install-from-source for `xmtp`
- `.tako/`: local, ignored runtime state

## Working Agreements

- Commit and push on every meaningful update (keep changes small and easy to review).
- Keep `index.html` in sync with current behavior, usage, and configuration.
- Keep `FEATURES.md` in sync with reality (stability + test criteria) whenever features change.
- When changing CLI flags or env vars, update `README.md`, `index.html`, and `FEATURES.md` together.

## Lessons Learned (append-only)

Add new notes at the top using `YYYY-MM-DD`, with a short title and a few bullets:

### YYYY-MM-DD — Title

- What happened:
- Fix:
- Prevention:

### 2026-02-10 — Keep local XMTP DBs out of git

- What happened: local `*.db3` files were easy to accidentally leave in the repo root.
- Fix: ignore `*.db3`, `*.db3-wal`, and `*.db3-shm`.
- Prevention: treat all local XMTP DB artifacts and `.tako/config.json` as sensitive runtime state.
