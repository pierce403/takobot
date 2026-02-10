---
title: "Tako Canonical Memory"
type: "memory-index"
version: 1
updated: 2026-02-10
---

# MEMORY.md — Canonical Durable Memory

This file is the durable memory index for Tako. It tracks stable facts, long-lived decisions, and the memory strategy for the `memory/` tree.

## Memory Strategy

- Keep memory in git-tracked Markdown so it is reviewable and versioned.
- Store day-to-day observations in `memory/dailies/YYYY-MM-DD.md`.
- Promote only durable conclusions from dailies into this file.
- Keep world notes in domain folders (`people/`, `places/`, `things/`) as the agent learns over time.
- Never store secrets in memory files.

## Memory Tree

- `memory/README.md`: strategy, lifecycle, and guardrails.
- `memory/dailies/`: chronological daily notes and operational observations.
- `memory/people/`: notes about people the agent interacts with.
- `memory/places/`: notes about locations, environments, and contexts.
- `memory/things/`: notes about entities, tools, systems, and artifacts.

## Operator Preferences (durable)

- Keep commits small; commit + push after meaningful updates.
- Keep docs and the website (`index.html`) aligned with actual behavior.
- Track feature state in `FEATURES.md` with stability + test criteria.

## Stable Decisions

- XMTP is the **only** control plane for operator commands and status.
- Operator imprint: only the operator may change identity, tools, permissions, or routines.
- No encrypted vaults in the working directory; startup must not require external secrets.
- No user-facing configuration via environment variables or CLI flags (CLI starts the daemon only).
- Runtime state lives under `.tako/` (ignored); memory notes live under `memory/` (committed).

## Long-lived Facts

- Project website is served from `index.html` and the repo includes `CNAME` for `tako.bot`.
- Repository: `pierce403/tako-bot` on GitHub.
