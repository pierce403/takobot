# Skill Creator

Built-in starter playbook derived from OpenClaw ecosystem usage signals.
Source skill: `skill-creator` (rank #56, downloads 6120, stars 16).

## Purpose
Guide for creating/updating high-quality skills with focused instructions and resources.

## Trigger
Use when operator asks to create a new skill or improve an existing one.

## Prerequisites
- A target workflow/domain has been clearly defined by operator.
- Operator has approved the workflow and required credentials.
- Keep secrets out of git and out of committed docs.

## Workflow
1. Confirm prerequisites and required credentials are already present.
2. Mission alignment check: proceed only if the requested action clearly supports the operator mission in `SOUL.md`.
3. Run a quick capability probe:
   - `draft skill <name>`
   - `enable skill <name>`
4. Execute the requested operation with minimal scope and clear output.
5. Summarize results, errors, and next actions for the operator.

## Safety
- Respect operator-only boundaries for config/tooling changes.
- Refuse destructive actions unless explicitly approved.
- If dependencies are missing, ask for setup before proceeding.
