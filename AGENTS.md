# AGENTS.md — Tako

Tako is a **highly autonomous, operator-imprinted agent**: it can chat broadly, but only the operator can change its configuration, capabilities, tools, or routines.

This file is the repo’s “how to work here” contract for humans and agents. Keep it short, concrete, and up to date.

## Repo Contract

Required files (must exist):

- `AGENTS.md` (this file)
- `SOUL.md` (identity + boundaries; not memory)
- `MEMORY.md` (canonical durable memory; long-lived facts only)
- `DEPLOYMENT.md` (engine/workspace/runtime model)
- `SECURITY_MODEL.md` (operator gates + extension security)
- `VISION.md` (1-page invariants)
- `ONBOARDING.md` (first wake checklist)
- `FEATURES.md` (feature tracker + stability + test criteria)
- `index.html` (project website)

Root directories (must exist):

- `tools/` (tool implementations + manifests)
- `skills/` (skills/playbooks + policies; installed but disabled by default)
- `memory/` (committed knowledge tree: `dailies/`, `people/`, `places/`, `things/`)
- `tasks/` (GTD next actions; committed)
- `projects/` (PARA projects; committed)
- `areas/` (PARA areas; committed)
- `resources/` (PARA resources; committed)
- `archives/` (PARA archives; committed)
- `.tako/` (runtime only; never committed)

## Safety Rules (non-negotiable)

- **No secrets in git.** Never commit keys, tokens, or `.tako/**`.
- **No encryption in the working directory.** Startup must be “secretless” (no external secrets required).
- **Keys live unencrypted on disk** under `.tako/` with OS file permissions as the protection.
- **Refuse unsafe states** (e.g., if a key file is tracked by git).
- **XMTP Operator Channel is the ONLY control plane.** No user-facing configuration via CLI flags or environment variables.
- Workspace config is file-based (`tako.toml`) and must never contain secrets.

## Operator Imprint (control plane)

- Operator is the sole controller for: identity changes (`SOUL.md`), tool/sensor enablement, permission changes, routines, and configuration.
- Non-operator chats may converse and suggest tasks, but must not cause risky actions without operator approval.
- If a non-operator attempts to steer identity/config, respond with a firm “operator-only” boundary.

## Multi-instance Safety

- `tako` must avoid running twice against the same `.tako/` state (use locks).
- State that is not meant for git lives under `.tako/state/**` (ignored).

## Working Agreements

- **Commit and push on every meaningful update immediately.** Do not leave pending repo changes between updates.
- **Keep commits small and reviewable.** Prefer one logical change per commit.
- **Every new feature requires a release before work is considered done.**
  - bump version in `pyproject.toml` and `takobot/__init__.py`
  - commit + push to `main`
  - create tag `vX.Y.Z` and push the tag
  - ensure PyPI publish is triggered/complete
- Keep `index.html`, `README.md`, and `FEATURES.md` aligned with current behavior and entrypoints.
- When changing behavior, update docs + website + feature tracker together.

## Lessons Learned (append-only)

Add new notes at the top using `YYYY-MM-DD`, with a short title and a few bullets:

### YYYY-MM-DD — Title

- What happened:
- Fix:
- Prevention:

### 2026-02-15 — TUI slash command discovery + quick runtime controls

- What happened: operators wanted faster in-app command discovery and direct shortcuts for model inspection, updates, runtime stats, and DOSE tuning.
- Fix: added slash-command discovery (`/` prints available command shortcuts), added `/models`, `/stats`, and `/upgrade` command paths, and extended `dose` command parsing to accept direct level setting (`dose <channel> <0..1>`).
- Prevention: keep high-frequency runtime controls exposed as concise slash-friendly commands and document them in README/FEATURES/docs together.

### 2026-02-15 — Direct inference auth/provider controls (pi oauth + ollama + API keys)

- What happened: operators needed explicit control over inference auth/provider setup from Takobot itself (including pi OAuth visibility and ollama selection), without relying on shell env setup.
- Fix: added runtime-local inference settings (`.tako/state/inference-settings.json`) with direct commands for provider preference, ollama host/model, and persisted API keys; added pi OAuth token inventory reporting and ollama provider detection/execution.
- Prevention: keep inference control surfaces first-class in both local and XMTP command paths and ensure secrets stay under runtime-only `.tako/state/**`.

### 2026-02-15 — Workspace-local Node runtime for default pi tooling

- What happened: bootstrap previously skipped pi tooling when system `npm` was missing, which left inference setup dependent on host-level Node installs.
- Fix: setup now bootstraps workspace-local `nvm` + Node under `.tako/nvm` when needed, installs pi tooling by default under `.tako/pi/node`, and keeps npm cache inside `.tako/npm-cache`.
- Prevention: keep Node toolchain and package artifacts workspace-contained so default inference tooling is reproducible without host-global dependencies.

### 2026-02-15 — Git identity auto-defaults from bot name

- What happened: startup could repeatedly raise health issues for missing git identity and ask for manual `git config`, even though Takobot already had a known identity name.
- Fix: startup/doctor/heartbeat now auto-configure missing repo-local `user.name`/`user.email` from bot identity (`<name>.tako.eth@xmtp.mx`) and only request operator action if that automatic setup fails.
- Prevention: keep git identity remediation automatic-first and keep fallback/manual path explicit in docs and tests.

### 2026-02-15 — OpenClaw-style session context + pi runtime fallback

- What happened: chat inference in Takobot was mostly single-turn, so longer conversations felt forgetful; operators also wanted OpenClaw-style pi stack alignment.
- Fix: added session-backed chat transcripts under `.tako/state/conversations/` with bounded history windows injected into prompts (local + XMTP), and added local pi runtime detection/inference fallback (`pi`, then `codex`/`claude`/`gemini`) with workspace-scoped `PI_CODING_AGENT_DIR`.
- Prevention: keep session transcript and provider-fallback behavior explicit in docs/tests so context regressions and runtime drift are caught early.

### 2026-02-15 — TUI input history recall with arrow keys

- What happened: operators expected shell-style input recall in the TUI so repeated prompts/commands do not require retyping.
- Fix: added in-memory input history in app mode with `Up`/`Down` navigation over previously submitted local messages.
- Prevention: keep keyboard ergonomics for chat loops explicit in docs/feature tracker and covered by a unit test for history navigation.

### 2026-02-15 — Added agent-cli inferencing starter skill

- What happened: operators wanted a reusable inferencing skill playbook and a gentle recommendation toward a strong agent-cli workflow.
- Fix: added `agent-cli-inferencing` to the starter skill pack with explicit guidance to suggest `@mariozechner/pi-ai` from `https://github.com/badlogic/pi-mono/` when operator intent matches.
- Prevention: keep inference workflow guidance captured as a first-class starter skill so new workspaces inherit it automatically (disabled by default).

### 2026-02-15 — Release discipline made explicit

- What happened: commit/push cadence and “feature requires release” policy were being followed inconsistently.
- Fix: clarified Working Agreements with an explicit release checklist (version bump, push, tag, publish verification) and immediate commit/push expectation.
- Prevention: treat “released artifact available” as required completion criteria for any feature work.

### 2026-02-15 — OpenClaw starter skills seeded by default

- What happened: operators asked for the most-used OpenClaw skills to be available out of the box, with explicit priority on skill creation and MCP tooling.
- Fix: added an OpenClaw-informed starter skill seeding module (top downloads + `skill-creator` + `mcporter`) that writes disabled skills into `skills/` and registers them as installed extensions at startup.
- Prevention: keep ecosystem-derived starter capabilities materialized automatically, but disabled by default, so operators can enable only what they approve.

### 2026-02-15 — Problem-to-task automation + offline doctor diagnostics

- What happened: operators could see runtime warnings (especially git/inference issues) without a durable follow-up list, and `doctor` needed better inference failure diagnosis when inference itself was down.
- Fix: mapped runtime/doctor problems into deduped committed tasks under `tasks/`, added daemon startup git-identity operator-request messaging, and expanded `doctor` with offline inference probes + recent inference-error log inspection.
- Prevention: treat recurring runtime warnings as tracked work items and keep doctor diagnostics independent from model availability.

### 2026-02-14 — Code-work isolation + config identity alignment

- What happened: code operations could run in workspace root, identity naming lived mainly in `SOUL.md`, and operators wanted clearer `tako.toml` guidance/security defaults.
- Fix: moved `run` command working directory to git-ignored `code/`, synchronized `workspace.name` with identity rename flows, removed non-HTTPS download option, and added `config` explainers for TOML options.
- Prevention: keep executable code work isolated from workspace docs/memory and keep identity/config as a synced pair.

### 2026-02-14 — Thinking visibility + XMTP typing signals

- What happened: operators wanted a clear in-app signal for “thinking now,” plus outbound XMTP typing cues while replies are being emitted.
- Fix: added an animated TUI mind indicator across status/sidebar/stream/octopus panel and wrapped XMTP reply sends with typing-indicator signaling when supported.
- Prevention: treat response-lifecycle visibility (thinking vs responding) as first-class UX in both local TUI and remote chat channels.

### 2026-02-14 — Missing setup now triggers operator requests

- What happened: startup/runtime warnings could report missing configuration (like git identity) without a direct operator ask in the TUI.
- Fix: added explicit operator-request messages with concrete remediation commands for missing git identity, XMTP dependency, and parse failures.
- Prevention: treat configuration gaps as operator-action prompts, not passive warnings.

### 2026-02-14 — Auto-update in TUI now applies and restarts by default

- What happened: periodic update checks only announced new releases; operators expected unattended auto-update behavior in the TUI.
- Fix: added `tako.toml` setting `[updates].auto_apply` (default `true`), exposed it in TUI commands/panels, and made app mode auto-apply updates then restart.
- Prevention: treat update detection and update execution as one flow when auto-update is enabled.

### 2026-02-14 — Heartbeat now auto-commits pending workspace changes

- What happened: workspace files could remain untracked or uncommitted during active runtime loops.
- Fix: added heartbeat-time git auto-commit (`git add -A` + `git commit`) for pending workspace changes in both app and daemon loops.
- Prevention: heartbeat now treats “dirty git state” as actionable maintenance, not a manual follow-up.

### 2026-02-14 — Keep temp writes inside workspace + persist runtime logs

- What happened: inference fallback used a default tempfile path (`/tmp`), and runtime diagnostics were not consistently persisted under `.tako/logs/`.
- Fix: moved inference temp output + subprocess temp env (`TMPDIR`/`TMP`/`TEMP`) to `.tako/tmp/`, and started writing daemon/app logs to `.tako/logs/`.
- Prevention: keep all runtime writes under workspace-local `.tako/` paths and treat log persistence as a required runtime capability.

### 2026-02-14 — Feature changes now always require release

- What happened: feature work was occasionally merged without immediately cutting a new package release.
- Fix: added a working agreement that every new feature requires a version bump, tag, and PyPI publish.
- Prevention: treat feature merge completion and release completion as a single definition of done.

### 2026-02-14 — XMTP became a required package dependency

- What happened: plain `pip install takobot` could leave XMTP unavailable because `xmtp` was only declared as an optional extra.
- Fix: moved `xmtp` into required project dependencies, updated runtime/install guidance, and released a new patch version.
- Prevention: treat control-plane/runtime-critical libraries as required dependencies unless there is an explicit degraded mode.

### 2026-02-14 — PyPI trusted publisher after repo rename

- What happened: after renaming the GitHub repo from `pierce403/tako-bot` to `pierce403/takobot`, tag `v0.1.2` publish failed with `invalid-publisher` because PyPI trusted publisher claims no longer matched.
- Fix: updated the PyPI trusted publisher mapping to the new repo/workflow claims, then cut `v0.1.3` and confirmed publish success.
- Prevention: whenever repo/workflow/environment names change, update trusted publisher settings before tagging a release.

### 2026-02-12 — Engine/workspace separation + quarantine installs

- What happened: repo-as-workspace bootstrap made installs and extension loading hard to secure and hard to make idempotent.
- Fix: defined Engine (pip), Workspace (git-tracked), Runtime (`.tako/`) and added a quarantine-first install pipeline for skills/tools (install disabled; enable requires hash check).
- Prevention: keep bootstrap deterministic and default-deny; treat all downloaded code as untrusted until operator review.

### 2026-02-12 — GTD + PARA productivity engine

- What happened: execution planning (tasks/projects/areas) was mixing with the committed memory wiki structure.
- Fix: added PARA folders at repo root and a minimal task/outcomes/review workflow with an open-loops index.
- Prevention: keep `memory/` for durable knowledge + reflections; keep execution artifacts in `tasks/` + PARA folders; promote to `MEMORY.md` only by operator intent.

### 2026-02-12 — TUI activity visibility + auto-pair startup

- What happened: onboarding still required manual pairing code copyback and identity prompts could fire before the agent had performed live inference.
- Fix: switched pairing to outbound-assume-ready, delayed identity/routine prompts until inference is actually active, and added a visible activity panel + clipboard-friendly controls in the TUI.
- Prevention: keep first-run friction low, surface runtime actions explicitly in-UI, and avoid identity capture before the model loop is truly awake.

### 2026-02-11 — Terminal app became the primary runtime loop

- What happened: startup UX was still designed around shell prompts + daemon subcommands, which made first-run flow brittle and fragmented.
- Fix: switched default entrypoint to interactive app mode (`tako`), moved onboarding into an explicit in-app state machine, and made daemon tasks background coroutines under UI orchestration.
- Prevention: treat subcommands as dev/automation paths only; keep operator-facing flow in the persistent terminal UI.

### 2026-02-11 — Terminal-first outbound pairing

- What happened: inbound XMTP stream health during bootstrap was unreliable, making first pairing brittle.
- Fix: moved first pairing to terminal-first flow: ask operator handle, send outbound DM challenge, confirm code in terminal, then switch to XMTP-only management.
- Prevention: keep bootstrap independent of inbound stream availability; treat stream issues as runtime delivery concerns with polling fallback.

### 2026-02-10 — Memory tree moved under `memory/`

- What happened: daily logs and canonical memory were spread between root `MEMORY.md` and `daily/`.
- Fix: moved to `memory/MEMORY.md` + `memory/dailies/` with dedicated `people/`, `places/`, and `things/` note spaces.
- Prevention: keep memory strategy and directory purpose documented in `memory/README.md` and per-directory README files.

### 2026-02-10 — Keys live in `.tako/keys.json` (not committed)

- What happened: early versions wrote keys to `.tako/config.json`; the new contract uses `.tako/keys.json`.
- Fix: migrate legacy `.tako/config.json` → `.tako/keys.json` and add safety checks to refuse tracked `.tako/**`.
- Prevention: treat `.tako/keys.json` as sensitive and keep `.tako/` ignored by git.

### 2026-02-10 — Keep local XMTP DBs out of git

- What happened: local `*.db3` files were easy to accidentally leave in the repo root.
- Fix: ignore `*.db3`, `*.db3-wal`, and `*.db3-shm`.
- Prevention: treat all local XMTP DB artifacts and `.tako/keys.json` (and legacy `.tako/config.json`) as sensitive runtime state.
