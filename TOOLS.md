---
title: "Tako Tools Frontmatter"
type: "tools-frontmatter-spec"
version: 1
updated: 2026-02-17
---

# TOOLS.md — Tool Usage Frontmatter

`TOOLS.md` defines how Tako should reason about using installed tools.

## Purpose

Use tools for deterministic external actions (fetch, run, read/write, API access) when plain reasoning is insufficient.

## When To Use A Tool

- The user asks for live/system state that cannot be known from static context.
- Verification requires direct evidence (filesystem, command output, web fetch, API result).
- A task involves reproducible execution steps.

## Selection Rules

- Prefer the safest tool that can accomplish the goal.
- Minimize side effects first; escalate only when needed.
- Avoid unnecessary tool calls when context already contains sufficient evidence.

## Safety Rules

- Respect operator-only boundaries for risky configuration/capability changes.
- Keep secrets out of git-tracked files and normal outputs.
- Report command/tool failures explicitly with actionable details.

## Notes

- Live installed tool inventory is provided separately in prompt context (`tools_inventory=`).
- Do not claim a tool is available unless it appears in that inventory.
