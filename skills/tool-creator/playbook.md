# Tool Creator

Built-in starter playbook derived from OpenClaw ecosystem usage signals.
Source skill: `tool-creator` (rank #57, downloads 6012, stars 14).

## Purpose
Guide for drafting, validating, and enabling new workspace tools safely.

## Trigger
Use when operator asks to create or refine a custom tool implementation.

## Prerequisites
- A concrete tool behavior contract is defined by operator intent.
- Operator has approved the workflow and required credentials.
- Keep secrets out of git and out of committed docs.

## Workflow
1. Confirm prerequisites and required credentials are already present.
2. Mission alignment check: proceed only if the requested action clearly supports the operator mission in `SOUL.md`.
3. Run a quick capability probe:
   - `draft tool <name>`
   - `enable tool <name>`
   - `review pending`
4. Execute the requested operation with minimal scope and clear output.
5. Summarize results, errors, and next actions for the operator.

## Safety
- Respect operator-only boundaries for config/tooling changes.
- Refuse destructive actions unless explicitly approved.
- If dependencies are missing, ask for setup before proceeding.
