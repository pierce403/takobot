# tasks/ — Tasks (GTD)

Tasks are single next-actions. Keep them small and concrete.

This folder is committed (git-tracked) as part of the execution system. Do not store secrets.

## File Format

One task per file:

- Path: `tasks/<id>-<slug>.md`
- Markdown body: optional notes/context
- YAML frontmatter (minimal schema):
  - `id`: stable identifier
  - `title`: short action title
  - `status`: `open` | `done` | `blocked` | `someday`
  - `project`: optional project name
  - `area`: optional area name
  - `created`: `YYYY-MM-DD`
  - `updated`: `YYYY-MM-DD`
  - `due`: optional `YYYY-MM-DD`
  - `tags`: optional list
  - `energy`: optional `low` | `medium` | `high`

Example:

```markdown
---
id: tsk-20260212-184501
title: "Fix XMTP inbound stream"
status: open
project: "tako stability"
area: "ops"
created: 2026-02-12
updated: 2026-02-12
due: 2026-02-13
tags:
  - xmtp
  - bug
energy: medium
---

# Fix XMTP inbound stream

- Notes...
```

