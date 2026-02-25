# ByteRover Knowledge

Built-in starter playbook derived from OpenClaw ecosystem usage signals.
Source skill: `byterover` (rank #10, downloads 16878, stars 39).

## Purpose
Store/query project knowledge via ByteRover context tree patterns.

## Trigger
Use when operator wants explicit knowledge curation and retrieval loops.

## Prerequisites
- ByteRover access is configured by operator.
- Operator has approved the workflow and required credentials.
- Keep secrets out of git and out of committed docs.

## Workflow
1. Confirm prerequisites and required credentials are already present.
2. Mission alignment check: proceed only if the requested action clearly supports the operator mission in `SOUL.md`.
3. Run a quick capability probe:
   - `run command -v byterover`
   - `run byterover --help`
4. Execute the requested operation with minimal scope and clear output.
5. Summarize results, errors, and next actions for the operator.

## Safety
- Respect operator-only boundaries for config/tooling changes.
- Refuse destructive actions unless explicitly approved.
- If dependencies are missing, ask for setup before proceeding.
