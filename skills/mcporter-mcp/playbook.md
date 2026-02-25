# MCP Tooling (mcporter)

Built-in starter playbook derived from OpenClaw ecosystem usage signals.
Source skill: `mcporter-mcp` (rank #24, downloads 8042, stars 15).

## Purpose
Use mcporter CLI to list/configure/auth/call MCP servers and tools.

## Trigger
Use when operator asks to integrate with MCP servers or call MCP tools directly.

## Prerequisites
- MCP server credentials/config are operator-approved and available.
- Operator has approved the workflow and required credentials.
- Keep secrets out of git and out of committed docs.

## Workflow
1. Confirm prerequisites and required credentials are already present.
2. Mission alignment check: proceed only if the requested action clearly supports the operator mission in `SOUL.md`.
3. Run a quick capability probe:
   - `run command -v mcporter`
   - `run mcporter list`
   - `run mcporter call <server.tool> --args '{"ping":true}'`
4. Execute the requested operation with minimal scope and clear output.
5. Summarize results, errors, and next actions for the operator.

## Safety
- Respect operator-only boundaries for config/tooling changes.
- Refuse destructive actions unless explicitly approved.
- If dependencies are missing, ask for setup before proceeding.
