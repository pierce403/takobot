# Tavily Search

Built-in starter playbook derived from OpenClaw ecosystem usage signals.
Source skill: `tavily-search` (rank #5, downloads 18815, stars 31).

## Purpose
AI-optimized web search using Tavily API.

## Trigger
Use when high-signal web search is required and Tavily is configured.

## Prerequisites
- Tavily API key is configured by operator.
- Operator has approved the workflow and required credentials.
- Keep secrets out of git and out of committed docs.

## Workflow
1. Confirm prerequisites and required credentials are already present.
2. Mission alignment check: proceed only if the requested action clearly supports the operator mission in `SOUL.md`.
3. Run a quick capability probe:
   - `run command -v tavily-search`
   - `run tavily-search --help`
4. Execute the requested operation with minimal scope and clear output.
5. Summarize results, errors, and next actions for the operator.

## Safety
- Respect operator-only boundaries for config/tooling changes.
- Refuse destructive actions unless explicitly approved.
- If dependencies are missing, ask for setup before proceeding.
