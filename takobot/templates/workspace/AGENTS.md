# AGENTS.md — Tako Workspace Contract

Tako is a highly autonomous, operator-imprinted agent. It can chat broadly, but only the operator can change identity/config/tools/permissions/routines.

## Workspace Layout

Required files:

- `AGENTS.md`
- `SOUL.md`
- `MEMORY.md` (memory-system frontmatter spec)
- `ONBOARDING.md`
- `tako.toml` (no secrets)

Required directories:

- `memory/` (`dailies/`, `world/`, `reflections/`, `contradictions/`)
- `tasks/`, `projects/`, `areas/`, `resources/`, `archives/` (execution structure)
- `tools/`, `skills/` (workspace extensions; operator-approved installs are enabled)
- `.tako/` (runtime only; never committed)

## Memory Rules

- All memory markdown must live under `memory/`.
- `MEMORY.md` defines memory placement; keep it loaded as operating frontmatter.
- Keep execution artifacts out of memory directories.

## Safety Rules

- No secrets in git.
- No `.tako/**` in git.
- Runtime keys/tokens remain under `.tako/` with file permissions.

## Runtime Git Hygiene

- Heartbeat auto-commits pending workspace changes when safe.
- World-watch deterministic notes are written under `memory/world/`.
- Stage transitions (`[life].stage` in `tako.toml`) are logged to `memory/dailies/`.
