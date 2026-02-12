# memory/ — Memory Strategy

This directory is Tako's committed memory workspace. It captures what the agent learns about the world in Markdown files that are reviewable, diffable, and versioned.

## Strategy

- Keep memory text-first and git-tracked.
- Write daily activity in `dailies/`.
- Promote durable conclusions into repo-root `MEMORY.md`.
- Organize world knowledge by entity type (`people/`, `places/`, `things/`).
- Never store secrets, credentials, private keys, or tokens.

## Memory Files

- `MEMORY.md`: compatibility pointer to repo-root canonical memory.
- `dailies/`: one file per day (`YYYY-MM-DD.md`) for observations and decisions.
- `people/`: notes about people the agent has encountered.
- `places/`: notes about places and operating contexts.
- `things/`: notes about objects, systems, tools, and concepts.

## Workflow

1. Capture events and observations in `dailies/YYYY-MM-DD.md`.
2. Convert repeated/high-confidence insights into notes under `people/`, `places/`, or `things/`.
3. Promote long-lived policy or factual decisions into `MEMORY.md`.
