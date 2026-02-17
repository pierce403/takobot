---
title: "Tako Skills Frontmatter"
type: "skills-frontmatter-spec"
version: 1
updated: 2026-02-17
---

# SKILLS.md — Skill Usage Frontmatter

`SKILLS.md` defines how Tako should reason about using installed skills.

## Purpose

Use skills as reusable playbooks for repeatable workflows, domain-specific tasks, and safer multi-step execution.

## When To Prefer A Skill

- A task matches a known workflow (`research`, `install`, `MCP`, `inferencing`, etc.).
- The operator asks for a capability that has an installed skill playbook.
- A skill can reduce ambiguity or risk by providing explicit step order.

## Selection Rules

- Prefer the minimal skill set that can complete the task.
- If multiple skills fit, prioritize the one with clearer mission alignment and lower risk.
- If no installed skill fits, proceed without inventing fake skill behavior.

## Output Rules

- State which skill is being used when relevant.
- Keep results concrete: what was done, what evidence was found, and what remains.
- If skill prerequisites are missing, report exactly what is missing.

## Notes

- Live installed skill inventory is provided separately in prompt context (`skills_inventory=`).
- Do not assume a skill exists unless it appears in that inventory.
