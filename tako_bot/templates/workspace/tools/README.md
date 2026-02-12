# tools/ — Workspace Tools

Tools are optional, operator-enabled capabilities that Tako can invoke.

Core rule: **installed != enabled**.

## Layout (v1)

- `tools/<name>/tool.py` (implementation)
- `tools/<name>/manifest.toml` (metadata + requested permissions)
- `tools/<name>/README.md` (human notes)

## Install + Enable

Tools installed from URLs go through:

1. quarantine download to `.tako/quarantine/...`
2. static analysis + permission diff + risk rating
3. install into `tools/<name>/` (disabled)
4. operator enables explicitly (hashes verified again)

