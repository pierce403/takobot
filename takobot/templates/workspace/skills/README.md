# skills/ — Workspace Skills

Skills are operator-approved playbooks, prompts, and helpers that make Tako better at specific workflows.

Core rule: **installed != enabled**.

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

