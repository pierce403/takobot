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
- If `git` is available and `.git/` is missing, it initializes git, writes `.gitignore`, and commits the initial workspace (auto-configuring repo-local fallback identity if needed).
- It ensures a git-ignored `code/` directory exists for cloned repos and ephemeral code work.
- It ends by running `.venv/bin/takobot` (interactive TUI main loop).

## Running Tako

From the workspace root:

- `.venv/bin/takobot` starts the interactive TUI (the main loop).
- `takobot doctor`, `takobot run`, etc exist for developer/automation use, but the default UX is the TUI.
- Heartbeat loops (`takobot` app and `takobot run`) auto-commit pending workspace changes (`git add -A` + `git commit`) and verify repo cleanliness after commit.
- If git identity is missing during heartbeat commits, Tako auto-configures local repo identity (`Takobot <takobot@local>`) and retries.
- Local/XMTP `run` commands execute in `code/` by default.
- `takobot doctor` performs offline inference diagnostics (CLI probes + recent inference error scan) and records detected issues into `tasks/`.
- App/daemon startup seeds an OpenClaw starter skill pack into `skills/`, registers entries, and auto-enables installed extensions.

## Update Model

- Workspace updates are git-native (your repo history).
- Engine updates are package-native (upgrade `takobot` inside `.venv/`).
- App mode periodically checks for package updates and, when `tako.toml` has `[updates].auto_apply = true`, auto-applies updates and restarts itself.
- Templates never overwrite user edits; drift is logged to the daily log.
