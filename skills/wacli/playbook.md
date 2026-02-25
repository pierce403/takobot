# WhatsApp CLI (wacli)

Built-in starter playbook derived from OpenClaw ecosystem usage signals.
Source skill: `wacli` (rank #4, downloads 19943, stars 45).

## Purpose
Send WhatsApp messages and search/sync WhatsApp history via wacli CLI.

## Trigger
Use when the operator explicitly requests WhatsApp automation using CLI tooling.

## Prerequisites
- Operator has already configured/authorized wacli.
- Operator has approved the workflow and required credentials.
- Keep secrets out of git and out of committed docs.

## Workflow
1. Confirm prerequisites and required credentials are already present.
2. Mission alignment check: proceed only if the requested action clearly supports the operator mission in `SOUL.md`.
3. Run a quick capability probe:
   - `run command -v wacli`
   - `run wacli --help`
4. Execute the requested operation with minimal scope and clear output.
5. Summarize results, errors, and next actions for the operator.

## Safety
- Respect operator-only boundaries for config/tooling changes.
- Refuse destructive actions unless explicitly approved.
- If dependencies are missing, ask for setup before proceeding.
