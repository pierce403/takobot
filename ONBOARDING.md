# ONBOARDING.md — First Wake Checklist

This checklist defines first-wake success for a Tako workspace.

## Done When

- [ ] `.tako/` runtime structure exists (`locks/`, `logs/`, `tmp/`, `state/`, `xmtp-db/`) and `.tako/keys.json` exists.
- [ ] `MEMORY.md` exists at repo root and is used as memory-system frontmatter.
- [ ] All memory markdown writes are under `memory/`.
- [ ] Daily log exists at `memory/dailies/YYYY-MM-DD.md`.
- [ ] Stage exists in `tako.toml` (`[life].stage`).
- [ ] Hatchling onboarding collected: name, purpose, XMTP handle yes/no.
- [ ] After onboarding completion, stage moved to `child` and was logged in daily notes.
- [ ] Child-stage world learning is active (RSS world watch -> `memory/world/` notebook + briefings).

## Onboarding Flow (Stage-Aware)

1. `BOOTING`
2. `ONBOARDING_IDENTITY` (name + purpose)
3. `ASK_XMTP_HANDLE` (yes/no)
4. `PAIRING_OUTBOUND` (if yes)
5. `PAIRED` or local-only fallback
6. `RUNNING`

Mission objectives can be tuned after onboarding via `mission show|set|add|clear`.

## Life Stages

- `hatchling`: curious, small, gentle
- `child`: world learning + notebook
- `teen`: assumptions + contradictions
- `adult`: output/economic focus

Stage transitions:

- persist to `tako.toml` (`[life].stage`)
- append transition note to `memory/dailies/YYYY-MM-DD.md`
- update runtime policy (routines, cadence, budgets, DOSE baseline multipliers)

## Runtime Notes

- Runtime state stays under `.tako/` and is never committed.
- Memory notes stay under `memory/` and are committed.
- Execution artifacts stay under `tasks/`, `projects/`, `areas/`, `resources/`, `archives/`.
