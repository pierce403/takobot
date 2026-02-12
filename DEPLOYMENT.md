# DEPLOYMENT.md — Engine vs Workspace vs Runtime

## Terms

- **Engine**: the Python package (`tako`) installed into a local venv. This is the TUI + cognition loops + XMTP runtime + tool plumbing.
- **Workspace**: git-tracked Markdown + config + optional local code (`tools/` + `skills/`).
- **Runtime state**: `.tako/` (ignored). Holds keys, local DBs, locks, and runtime indexes.

## Bootstrap (curl | bash)

The supported "fresh start" is:

- Run `setup.sh` from an empty directory (or an existing Tako workspace).
- It creates a local `.venv/`.
- It installs the engine with `pip install tako` (PyPI). If that fails, it clones the engine source into `.tako/tmp/src/` and installs from there.
- It materializes the workspace from templates shipped inside the installed engine (`tako_bot/templates/**`) without overwriting existing files.
- If `git` is available and `.git/` is missing, it initializes git, writes `.gitignore`, and commits the initial workspace.
- It ends by running `.venv/bin/tako` (interactive TUI main loop).

## Running Tako

From the workspace root:

- `.venv/bin/tako` starts the interactive TUI (the main loop).
- `tako doctor`, `tako run`, etc exist for developer/automation use, but the default UX is the TUI.

## Update Model

- Workspace updates are git-native (your repo history).
- Engine updates are package-native (upgrade `tako` inside `.venv/`).
- Templates never overwrite user edits; drift is logged to the daily log.

