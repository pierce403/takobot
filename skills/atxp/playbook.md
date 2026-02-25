# ATXP

Built-in starter playbook derived from OpenClaw ecosystem usage signals.
Source skill: `atxp` (rank #1, downloads 23360, stars 7).

## Purpose
Access ATXP paid API tools for web search, image/music/video generation, and X/Twitter search.

## Trigger
Use when the operator asks for paid ATXP-backed search or media generation workflows.

## Prerequisites
- ATXP API credentials are available locally.
- Operator has approved the workflow and required credentials.
- Keep secrets out of git and out of committed docs.

## Workflow
1. Confirm prerequisites and required credentials are already present.
2. Mission alignment check: proceed only if the requested action clearly supports the operator mission in `SOUL.md`.
3. Run a quick capability probe:
   - `run command -v curl`
   - `run curl -fsSL https://api.atxp.example/health`
4. Execute the requested operation with minimal scope and clear output.
5. Summarize results, errors, and next actions for the operator.

## Safety
- Respect operator-only boundaries for config/tooling changes.
- Refuse destructive actions unless explicitly approved.
- If dependencies are missing, ask for setup before proceeding.
