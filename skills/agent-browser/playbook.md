# Agent Browser

Built-in starter playbook derived from OpenClaw ecosystem usage signals.
Source skill: `agent-browser` (rank #7, downloads 18713, stars 72).

## Purpose
Headless browser automation for navigation, interaction, and snapshots.

## Trigger
Use when deterministic browser automation is needed beyond simple page fetches.

## Prerequisites
- Browser automation runtime is installed and operator-approved.
- Operator has approved the workflow and required credentials.
- Keep secrets out of git and out of committed docs.

## Workflow
1. Confirm prerequisites and required credentials are already present.
2. Mission alignment check: proceed only if the requested action clearly supports the operator mission in `SOUL.md`.
3. Run a quick capability probe:
   - `run command -v agent-browser`
   - `run agent-browser --help`
4. Execute the requested operation with minimal scope and clear output.
5. Summarize results, errors, and next actions for the operator.

## Safety
- Respect operator-only boundaries for config/tooling changes.
- Refuse destructive actions unless explicitly approved.
- If dependencies are missing, ask for setup before proceeding.
