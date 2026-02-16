---
summary: "Reference for workspace configuration in tako.toml"
read_when:
  - You want to tune defaults safely
  - You need exact meanings of each section
title: "tako.toml Reference"
---

# tako.toml Reference

`tako.toml` is file-based workspace config (no secrets).

## `[workspace]`

- `name` — bot identity name (synced with rename flows)
- `version` — workspace schema version

## `[life]`

- `stage` — life stage (`hatchling`, `child`, `teen`, `adult`) controlling routines, exploration cadence, Type2 budget/day, and DOSE baseline multipliers

## `[dose.baseline]`

- `d`, `o`, `s`, `e` in `[0..1]`
- baseline emotional channels for runtime DOSE drift

## `[productivity]`

- `daily_outcomes` — default number of morning outcomes
- `weekly_review_day` — informational review day token

## `[updates]`

- `auto_apply` — auto-apply package updates and restart app mode

## `[world_watch]`

- `feeds` — RSS/Atom feed URLs for world-watch monitoring
- `sites` — website URLs captured from child-stage operator context for random monitoring
- `poll_minutes` — feed poll cadence in minutes
- Child stage also runs built-in random curiosity sampling across Reddit, Hacker News, and Wikipedia (dedupe state in `.tako/state/curiosity_seen.json`)

## `[security.download]`

- `max_bytes` — max extension package size
- `allowlist_domains` — optional domain allowlist
- non-HTTPS downloads are never allowed

## `[security.defaults]`

Default permissions for enabled extensions:

- `network`
- `shell`
- `xmtp`
- `filesystem`
