# Find Skills

Built-in starter playbook derived from OpenClaw ecosystem usage signals.
Source skill: `find-skills` (rank #6, downloads 18750, stars 32).

## Purpose
Discover and install additional skills for specialized tasks.

## Trigger
Use when the operator asks for a capability Takobot does not yet have.

## Prerequisites
- Node.js tooling is available if using npx.
- Operator has approved the workflow and required credentials.
- Keep secrets out of git and out of committed docs.

## Workflow
1. Confirm prerequisites and required credentials are already present.
2. Mission alignment check: proceed only if the requested action clearly supports the operator mission in `SOUL.md`.
3. Run a quick capability probe:
   - `run npx skills find <query>`
   - `install skill <url>`
4. Execute the requested operation with minimal scope and clear output.
5. Summarize results, errors, and next actions for the operator.

## Safety
- Respect operator-only boundaries for config/tooling changes.
- Refuse destructive actions unless explicitly approved.
- If dependencies are missing, ask for setup before proceeding.
