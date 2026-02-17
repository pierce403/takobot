# tools/ — Workspace Tools

Tools are optional, operator-enabled capabilities that Tako can invoke.

Core rule: **non-operator cannot change tool configuration**.

Built-in standard web tools:

- `web_search`: structured web discovery for live/current facts
- `web_fetch`: deterministic URL fetch + readable text extraction

## Layout (v1)

- `tools/<name>/tool.py` (implementation)
- `tools/<name>/manifest.toml` (metadata + requested permissions)
- `tools/<name>/README.md` (human notes)

## Install + Enable

Tools installed from URLs go through:

1. quarantine download to `.tako/quarantine/...`
2. static analysis + permission diff + risk rating
3. install into `tools/<name>/` (enabled after operator acceptance)
4. optional explicit re-enable remains available (`enable tool <name>`)
