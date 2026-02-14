---
title: "Tako Canonical Memory"
type: "memory-index"
version: 2
updated: 2026-02-12
---

# MEMORY.md — Canonical Durable Memory

This file is Tako's canonical durable memory index. It tracks stable facts, long-lived decisions, and the durable workflow contract.

Memory is git-tracked and reviewable. Never store secrets here.

## Memory Strategy

- Capture day-to-day observations in `memory/dailies/YYYY-MM-DD.md`.
- Promote only durable conclusions into this file.
- Keep world notes in `memory/people/`, `memory/places/`, and `memory/things/`.
- Keep execution structure (GTD + PARA) outside `memory/`:
  - `tasks/`, `projects/`, `areas/`, `resources/`, `archives/`

## Operator Preferences (durable)

- Keep commits small; commit + push after meaningful updates.
- Keep docs and the website (`index.html`) aligned with actual behavior.
- Track feature state in `FEATURES.md` with stability + test criteria.

## Stable Decisions

- Operator imprint: only the operator may change identity, tools, permissions, routines, and configuration.
- XMTP operator channel is the control plane when paired; non-operators can chat but cannot steer config.
- No encrypted vaults in the working directory; startup must not require external secrets.
- Runtime state lives under `.tako/` (ignored by git).
- Durable knowledge lives under `memory/` (committed).
- Execution structure lives under PARA directories at repo root (committed).

## Long-lived Facts

- Project website is served from `index.html` and the repo includes `CNAME` for `tako.bot`.
- Repository: `pierce403/takobot` on GitHub.
