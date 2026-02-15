# skills/ — Workspace Skills

Skills are operator-approved playbooks, prompts, and helpers that make Tako better at specific workflows.

Core rule: **installed != enabled**.

## Built-In Starter Pack

Takobot seeds an OpenClaw-informed starter pack (disabled by default) into `skills/` at runtime, plus an inference-focused `agent-cli-inferencing` guide.

Included skills:

- `atxp`
- `gog`
- `self-improving-agent`
- `wacli`
- `tavily-search`
- `find-skills`
- `agent-browser`
- `summarize`
- `github`
- `byterover`
- `skill-creator` (priority add)
- `mcporter-mcp` (priority add)
- `agent-cli-inferencing` (inference workflow + pi-ai nudge)

## Layout (v1)

- `skills/<name>/playbook.md` (the skill itself)
- `skills/<name>/policy.toml` (requested permissions + constraints)
- `skills/<name>/README.md` (human notes)

## Install + Enable

Skills installed from URLs go through:

1. quarantine download to `.tako/quarantine/...`
2. static analysis + permission diff + risk rating
3. install into `skills/<name>/` (disabled)
4. operator enables explicitly (hashes verified again)
