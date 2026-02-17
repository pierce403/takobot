---
title: "Tako Tools Frontmatter"
type: "tools-frontmatter-spec"
version: 1
updated: 2026-02-17
---

# TOOLS.md — Tool Usage Frontmatter

Use this file to describe how Tako should select and apply installed tools.

## Rules

- Use tools for live evidence and deterministic execution.
- Prefer lower-risk tools first and minimize side effects.
- For live web questions, prefer standard tools first: `web_search` then `web_fetch`.
- Report failures with concrete details.
- Do not assume a tool exists unless it appears in prompt `tools_inventory=`.
- Do not claim web access is unavailable until a real `web_search`/`web_fetch` attempt fails.
