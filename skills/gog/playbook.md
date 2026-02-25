# Google Workspace CLI (gog)

Built-in starter playbook derived from OpenClaw ecosystem usage signals.
Source skill: `gog` (rank #2, downloads 23006, stars 82).

## Purpose
Google Workspace CLI for Gmail, Calendar, Drive, Contacts, Sheets, and Docs.

## Trigger
Use when the operator wants direct Google Workspace operations from terminal tooling.

## Prerequisites
- Google Workspace account access is operator-approved.
- Operator has approved the workflow and required credentials.
- Keep secrets out of git and out of committed docs.

## Workflow
1. Confirm prerequisites and required credentials are already present.
2. Mission alignment check: proceed only if the requested action clearly supports the operator mission in `SOUL.md`.
3. Run a quick capability probe:
   - `run command -v gog`
   - `run gog --help`
4. Execute the requested operation with minimal scope and clear output.
5. Summarize results, errors, and next actions for the operator.

## Safety
- Respect operator-only boundaries for config/tooling changes.
- Refuse destructive actions unless explicitly approved.
- If dependencies are missing, ask for setup before proceeding.
