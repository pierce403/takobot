# DEPLOYMENT.md — Engine vs Workspace vs Runtime

## Terms

- **Engine**: the Python package (`takobot`, module `takobot`) installed into a local venv. This is the TUI + cognition loops + XMTP runtime + tool plumbing.
- **Workspace**: git-tracked Markdown + config + optional local code (`tools/` + `skills/`).
- **Runtime state**: `.tako/` (ignored). Holds keys, local DBs, locks, logs, local temp files, and runtime indexes.

## Bootstrap (curl | bash)

The supported "fresh start" is:

- Run `setup.sh` from an empty directory (or an existing Tako workspace).
- It creates a local `.venv/`.
- It attempts to install or upgrade the engine with `pip install --upgrade takobot` (PyPI). If that fails and no engine is already present, it clones the engine source into `.tako/tmp/src/` and installs from there.
- It materializes the workspace from templates shipped inside the installed engine (`takobot/templates/**`) without overwriting existing files.
- If `git` is available and `.git/` is missing, it initializes git, writes `.gitignore`, and commits the initial workspace.
- It ends by running `.venv/bin/takobot` (interactive TUI main loop).

## Running Tako

From the workspace root:

- `.venv/bin/takobot` starts the interactive TUI (the main loop).
- `takobot doctor`, `takobot run`, etc exist for developer/automation use, but the default UX is the TUI.
- Heartbeat loops (`takobot` app and `takobot run`) auto-commit pending workspace changes (`git add -A` + `git commit`) when the repo and git identity are configured.

## Update Model

- Workspace updates are git-native (your repo history).
- Engine updates are package-native (upgrade `takobot` inside `.venv/`).
- Templates never overwrite user edits; drift is logged to the daily log.
