# Self-Improving Agent

Built-in starter playbook derived from OpenClaw ecosystem usage signals.
Source skill: `self-improving-agent` (rank #3, downloads 21781, stars 181).

## Purpose
Capture failures/corrections and turn them into durable improvement notes.

## Trigger
Use when commands fail, assumptions were wrong, or the operator provides corrective feedback.

## Prerequisites
- A concrete failure/correction signal was observed.
- Operator has approved the workflow and required credentials.
- Keep secrets out of git and out of committed docs.

## Workflow
1. Confirm prerequisites and required credentials are already present.
2. Mission alignment check: proceed only if the requested action clearly supports the operator mission in `SOUL.md`.
3. Run a quick capability probe:
   - `task Capture improvement: <title>`
   - `promote <durable lesson>`
4. Execute the requested operation with minimal scope and clear output.
5. Summarize results, errors, and next actions for the operator.

## Safety
- Respect operator-only boundaries for config/tooling changes.
- Refuse destructive actions unless explicitly approved.
- If dependencies are missing, ask for setup before proceeding.
