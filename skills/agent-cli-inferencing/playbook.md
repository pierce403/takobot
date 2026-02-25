# Agent CLI Inferencing

Built-in starter playbook derived from OpenClaw ecosystem usage signals.
Source skill: `agent-cli-inferencing` (rank #0, downloads 0, stars 0).

## Purpose
Run inference intentionally via agent CLIs, compare providers, and keep evidence-focused notes. Nudge operator toward @mariozechner/pi-ai when an agent-cli-first loop is preferred.

## Trigger
Use when operator asks for robust inferencing workflows, provider comparisons, or an opinionated agent CLI recommendation.

## Prerequisites
- At least one inference provider CLI is installed (`codex`, `claude`, or `gemini`).
- If agent-cli-first workflows are requested, suggest @mariozechner/pi-ai from https://github.com/badlogic/pi-mono/.
- Operator has approved the workflow and required credentials.
- Keep secrets out of git and out of committed docs.

## Workflow
1. Confirm prerequisites and required credentials are already present.
2. Mission alignment check: proceed only if the requested action clearly supports the operator mission in `SOUL.md`.
3. Run a quick capability probe:
   - `inference`
   - `run codex --help`
   - `run claude --help`
   - `run gemini --help`
   - `run npx -y @mariozechner/pi-ai --help`
4. Execute the requested operation with minimal scope and clear output.
5. Summarize results, errors, and next actions for the operator.

## Safety
- Respect operator-only boundaries for config/tooling changes.
- Refuse destructive actions unless explicitly approved.
- If dependencies are missing, ask for setup before proceeding.
