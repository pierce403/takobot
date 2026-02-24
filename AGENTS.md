# AGENTS.md — Tako

Tako is a **highly autonomous, operator-imprinted agent**: it can chat broadly, but only the operator can change its configuration, capabilities, tools, or routines.

This file is the repo’s “how to work here” contract for humans and agents. Keep it short, concrete, and up to date.

## Repo Contract

Required files (must exist):

- `AGENTS.md` (this file)
- `SOUL.md` (identity + boundaries; not memory)
- `MEMORY.md` (canonical durable memory; long-lived facts only)
- `SKILLS.md` (skill usage frontmatter + governance)
- `TOOLS.md` (tool usage frontmatter + governance)
- `DEPLOYMENT.md` (engine/workspace/runtime model)
- `SECURITY_MODEL.md` (operator gates + extension security)
- `VISION.md` (1-page invariants)
- `ONBOARDING.md` (first wake checklist)
- `FEATURES.md` (feature tracker + stability + test criteria)
- `index.html` (project website)

Root directories (must exist):

- `tools/` (tool implementations + manifests)
- `skills/` (skills/playbooks + policies; starter + operator-approved installs are enabled)
- `memory/` (committed memory store: `dailies/`, `world/`, `reflections/`, `contradictions/`)
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
- **Operator control is available in terminal app + paired XMTP channel.** No user-facing configuration via CLI flags or environment variables.
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

### 2026-02-24 — XMTP display-name requests now bypass generic chat and trigger profile sync

- What happened: messages like `can you set your display name on XMTP yet?` could miss deterministic rename/profile handling and fall through to generic model answers, even when the operator intended immediate XMTP profile sync behavior.
- Fix: added explicit name-change request heuristics and XMTP profile-sync request detection so no-name XMTP profile requests trigger a direct profile sync to current identity with actionable follow-up guidance.
- Prevention: keep operator control intents (identity/profile) deterministic-first, using model classification as fallback only, and cover request/info-query separation with identity parser tests.

### 2026-02-24 — XMTP self-DM profile fallback now uses address-safe DM creation

- What happened: profile fallback could fail with `AddressValidation` when attempting self-DM creation via `new_dm(<inbox_id>)` on SDKs that require `new_dm(<0x address>)`.
- Fix: self-DM resolution now performs inbox-id lookup first, then falls back to account-address DM creation (plus identifier-based DM creation where available); added regression coverage for address-validated `new_dm` behavior.
- Prevention: keep DM creation path format-aware (inbox lookup vs address create) and preserve tests that fail when self-DM uses inbox IDs in address-validated SDK runtimes.

### 2026-02-24 — Rename-intent checks are now hint-gated and fallback diagnostics no longer pollute prompt history

- What happened: XMTP/local chat was invoking a separate identity-name intent inference call even on generic messages (for example `hi`), and repeated inference-unavailable fallback replies (with long error/log-path diagnostics) were being injected back into prompt history, increasing latency and timeout risk on later turns.
- Fix: added `looks_like_name_change_hint` gating before running model-based rename-intent classification (plus shorter intent timeout), and compacted verbose fallback diagnostic assistant turns to a short marker line when building prompt history context.
- Prevention: keep expensive intent-classifier inference behind high-signal hint gates and avoid feeding large operational diagnostics back into model context windows.

### 2026-02-24 — XMTP profile fallback now matches Converge DM + Convos group specs

- What happened: DM fallback profile updates could miss Converge custom-content transport, and Convos group profile upserts depended on wrapper-level `appData` methods that are absent in some XMTP SDK wrappers.
- Fix: DM profile fallback now sends `converge.cv/profile:1.0` custom metadata payloads in 1:1 conversations, while group fallback keeps Convos `appData` protobuf upserts and now uses wrapper `_ffi` appData APIs when needed; added explicit `protobuf` dependency and unit coverage for both DM and group metadata paths.
- Prevention: keep DM and group profile transport separated by conversation type, avoid plain-text JSON profile fallbacks, and preserve tests that assert both Converge DM sends and Convos group upserts.

### 2026-02-23 — Pi legacy `tools/` migration prompts are auto-remediated before inference

- What happened: pi runtime started pausing with `Press any key to continue...` when deprecated custom `tools/` directories were present (global or project-local), which blocked non-interactive Takobot inference.
- Fix: capability sync now targets `extensions/` (with workspace legacy `tools/` fallback), removes legacy `tools/` symlink mappings, and migrates project `.pi/tools` custom entries into `.pi/extensions` before inference runs.
- Prevention: keep pi capability sync aligned with upstream extension-system migrations and cover legacy tools-remediation behavior with inference runtime unit tests.

### 2026-02-23 — Pi inference now fast-fails interactive prompts in non-interactive runs

- What happened: some pi runtime states emitted interactive CLI prompts (for example `Press any key to continue...`) during non-interactive inference calls, causing stream turns to stall until timeout and then fail over noisily.
- Fix: inference subprocesses now run with non-interactive stdin (`DEVNULL`) and `CI=1`; stream processing detects interactive prompt lines, terminates the subprocess immediately, and skips stream->sync fallback for this failure class.
- Prevention: keep non-interactive subprocess guards centralized in inference runners and test interactive-prompt detection paths so regressions fail fast instead of timing out.

### 2026-02-23 — `run`/`exec` now use workspace root and include workspace pi bins on PATH

- What happened: operator `exec` commands were forced to `code/` and could not resolve `pi`/`pi-ai` binaries, causing misleading "command not found" errors even when inference runtime was installed.
- Fix: `run`/`exec` now execute from workspace root, and command PATH prepends workspace-local pi runtime bins (`.tako/pi/node/node_modules/.bin`) plus latest workspace nvm node bin when present.
- Prevention: keep command-surface cwd semantics aligned with operator expectations, and test command PATH prefix behavior so local runtime CLIs remain reachable.

### 2026-02-23 — Paired startup now sends operator "back online" XMTP status ping

- What happened: when Tako restarted in paired mode, operators had to infer liveness manually from silence unless they sent a prompt first.
- Fix: daemon startup now sends a best-effort operator DM on XMTP with quick runtime state (version, stage, inference readiness, jobs/tasks counts, and wallet address), with address-first then inbox-id fallback recipient resolution.
- Prevention: keep operator liveness signaling explicit on paired startup and cover message composition/send fallback behavior with CLI resilience tests.

### 2026-02-23 — Workspace pi auth sync now prefers fresh `~/.pi` and stops clobbering existing openai-codex entries

- What happened: operators could complete pi/OpenAI auth in CLI, but Takobot could keep using stale workspace credentials because workspace auth only copied from `~/.pi` when missing, and Codex OAuth import could overwrite an existing workspace `openai-codex` token set.
- Fix: workspace pi auth sync now refreshes from newer `~/.pi` auth files, and Codex OAuth import only fills missing/incomplete `openai-codex` data instead of overwriting an existing complete workspace entry.
- Prevention: keep workspace auth as source of truth once populated, treat newer `~/.pi` auth as a refresh signal, and cover both flows with runtime auth-sync unit tests.

### 2026-02-23 — Added `exec` alias and proactive inference auto-repair in XMTP chat fallback

- What happened: operator workflows over XMTP were relying on `run` only, and daemon chat fallback could return immediately when inference runtime was not ready without first attempting repair in that turn.
- Fix: added `exec` as a first-class alias of `run` across local TUI + XMTP command detection/help/docs, and updated XMTP chat reply flow to attempt bounded auto-repair (`auto_repair_inference_runtime` + runtime rediscovery) before sending fallback-only responses.
- Prevention: keep command-surface aliases aligned across app/daemon/docs/tests, and always attempt local runtime repair before asking operator for manual inference reauth.

### 2026-02-23 — Inference fallback now includes non-inference OpenAI reauth guidance

- What happened: when OpenAI/Codex OAuth refresh tokens expired or were already consumed, fallback chat copy stayed generic and `inference login` could short-circuit on stale "auth-ready" state, leaving operators without a clear offline recovery path.
- Fix: added refresh-failure detection in inference fallback messaging and surfaced explicit recovery steps (`inference login force`, `inference login answer <text>`, `inference refresh`, `inference auth`); added `inference login force` handling so local TUI can force interactive reauth even when auth files exist.
- Prevention: keep auth-failure pattern detection in tests, keep operator recovery steps deterministic in fallback replies, and avoid treating "auth file exists" as equivalent to "token is valid".

### 2026-02-23 — Pi chat now falls back from stream mode to sync mode on CLI incompatibilities

- What happened: some bot workspaces had pi CLI variants that exited early in stream-json mode (`--mode json` / thinking flag mismatches), causing Type1 chat turns to fail with provider-exhausted errors.
- Fix: pi streaming now falls back to sync pi execution when stream invocation fails, and thinking-level argument mapping now downgrades unsupported levels (`minimal`→`low`, `xhigh`→`high`) when the CLI help indicates older accepted values.
- Prevention: keep pi invocation compatibility tested across stream/sync paths, include retry paths for optional-flag incompatibilities, and preserve stderr/stdout tail logging for failed command attempts.

### 2026-02-23 — Convos profile fallback now writes group appData metadata (not chat messages)

- What happened: fallback profile updates were being emitted as text/JSON chat content, which surfaced in conversation history and did not apply as Convos profile metadata.
- Fix: replaced message-content fallback with Convos-compatible `group.appData` upsert flow (base64url decode, optional Convos compression decode, `ConversationCustomMetadata` profile upsert by `inboxId` bytes, re-encode, `updateAppData`).
- Prevention: keep profile fallback metadata-only (never chat-message JSON), preserve Convos compression compatibility, and test profile upsert behavior against group appData paths.

### 2026-02-19 — XMTP profile fallback now uses DM metadata messages for SDKs without profile writes

- What happened: some runtime environments still lacked XMTP profile metadata write methods, so display name/avatar updates could remain invisible to clients expecting profile data even after local sync attempts.
- Fix: added Takobot profile fallback publishing (profile metadata JSON messages) to self-DM + known peers during profile sync, plus active-DM publish on inbound chat paths; added parser/ignore logic so inbound profile metadata messages do not trigger chat replies.
- Prevention: keep profile sync multi-path (SDK profile API verify/repair + DM metadata fallback), persist fallback broadcast state under `.tako/state/xmtp-profile-broadcast.json`, and test fallback publish behavior alongside API-present/API-missing sync tests.

### 2026-02-19 — XMTP profile sync now verifies before writing and reports SDK limits

- What happened: operators could request XMTP name/avatar updates, but sync behavior was write-first and status logs could not clearly distinguish “already synced” from “SDK cannot update profile metadata.”
- Fix: XMTP profile sync now attempts a read/verify pass first, updates only when mismatched, and records verification/update API availability plus observed values in `.tako/state/xmtp-profile.json`; runtime/TUI logs now explicitly report `already in sync` vs `read-only/no update API`.
- Prevention: keep verify/repair behavior covered with unit tests (matched profile skip-write + mismatch repair), and keep docs explicit that some installed XMTP Python SDK builds expose inbox state but no profile metadata write methods.

### 2026-02-19 — XMTP update now requests TUI restart after apply

- What happened: operator `update` over XMTP applied package changes but still replied with manual restart copy, so paired TUI sessions could remain on stale code until manual restart.
- Fix: added runtime hook wiring for XMTP `update` apply flow so daemon command handling can request terminal restart after reply delivery when hosted inside paired TUI runtime; daemon-only mode still reports manual restart guidance.
- Prevention: keep XMTP command flows aware of hosting mode via explicit hooks and cover callback invocation paths with CLI resilience tests.

### 2026-02-19 — Name updates now use inference intent (not hardcoded phrase gates)

- What happened: operator rename handling depended on hardcoded name-change phrase recognition before inference, so broad requests could hit generic clarification even when intent was clear.
- Fix: removed phrase-gated name-change detection in local and XMTP operator chat flows; rename intent is now inference-classified with structured JSON (`intent` + `name`), and explicit follow-up prompts request the target name when omitted.
- Prevention: keep rename-intent parsing/prompt schema in unit tests and prefer model-based intent extraction for operator config changes where rigid phrase gates cause UX misses.

### 2026-02-19 — Natural-language cron jobs now run through heartbeat and XMTP controls

- What happened: operators could ask for recurring work in plain language, but there was no durable jobs store or command surface for scheduling/listing/removing/running jobs across terminal and XMTP.
- Fix: added a versioned jobs store at `.tako/state/cron/jobs.json`, natural-language schedule parsing (`every day at 3pm ...`, weekday/day-of-week variants), local `jobs` command controls, XMTP `jobs` controls, and heartbeat-time due-job claiming/queueing in app runtime.
- Prevention: keep jobs parsing/claim semantics and command detection under unit tests, and keep docs/website/feature tracker updated together whenever command surfaces expand.

### 2026-02-19 — XMTP profile sync now aligns identity name + avatar

- What happened: XMTP runtime had no dedicated profile-sync path, so identity renames in `SOUL.md` / `tako.toml` were not propagated to XMTP profile metadata and no first-class avatar artifact existed.
- Fix: added best-effort XMTP profile sync across startup, rebuild, pairing, and name-update flows; sync now derives display name from identity, generates deterministic avatar SVG at `.tako/state/xmtp-avatar.svg`, and records sync state at `.tako/state/xmtp-profile.json`.
- Prevention: keep profile sync wired into both daemon and TUI rename/pairing paths and keep unit tests for API-present/API-absent SDK behavior.

### 2026-02-19 — Pi runtime now enforces Node >=20 compatibility

- What happened: some fresh installs had system Node present but below pi package requirements, so workspace pi CLI installed but failed at runtime with syntax errors from `@mariozechner/pi-tui`.
- Fix: inference runtime discovery/bootstrap and `setup.sh` now treat Node `<20` as incompatible and auto-bootstrap workspace-local nvm/node before using pi; detection copy now reports compatible-node requirement explicitly.
- Prevention: keep Node-version compatibility checks in bootstrap/runtime paths and cover them with inference runtime tests so old-system-node environments auto-heal.

### 2026-02-19 — Fresh workspace launcher + Codex OAuth import now happen at startup

- What happened: fresh workspace materialization did not create a local `tako.sh` launcher, and Codex OAuth import into workspace pi auth could be skipped until a later pi invocation.
- Fix: added `tako.sh` to workspace templates with executable mode on creation, and moved pi auth sync (including Codex OAuth import) into runtime discovery so startup/refresh state reflects available auth immediately.
- Prevention: keep startup bootstrap assertions for workspace launcher presence and discovery-time auth sync behavior in tests so packaging/runtime regressions are caught before release.

### 2026-02-17 — Skills/tools frontmatter now participates in chat context stack

- What happened: prompt context previously emphasized identity (`SOUL.md`) and memory (`MEMORY.md`) but lacked explicit capability-governance frontmatter, so skill/tool fallback behavior could drift.
- Fix: added root `SKILLS.md` + `TOOLS.md`, added workspace templates for both, and wired local/XMTP chat prompts to include bounded excerpts plus live installed capability inventories from `skills/` and `tools/`.
- Prevention: keep capability frontmatter files as required workspace contract docs and test prompt-context parity for both local and XMTP chat paths.

### 2026-02-17 — Child-stage chat now avoids repeated startup interrogation

- What happened: child-stage conversation openings could feel repetitive and unnatural (for example repeatedly asking channel clarification and similar profile questions on startup).
- Fix: child-stage prompt policy now enforces answer-first behavior, explicitly avoids channel/surface clarification questions, and injects profile-context hints so already-asked/already-known topics are not repeated; profile followups now use a bounded cooldown and staged sequence (`intro -> focus -> websites`).
- Prevention: keep child persona constraints explicit in prompt templates and maintain deterministic followup throttling in `operator_profile` state/tests.

### 2026-02-17 — Chat context stack now includes SOUL and matches across TUI/XMTP

- What happened: local TUI chat prompts carried richer context (focus/RAG/mission metadata), while XMTP chat prompts were lighter and did not include `SOUL.md`, which created behavior drift across channels.
- Fix: added bounded `SOUL.md` excerpt loading for prompts and aligned XMTP chat context with TUI context blocks (`SOUL.md`, `MEMORY.md` frontmatter, focus summary, semantic RAG context, recent conversation, mission/stage metadata).
- Prevention: keep prompt-context schema explicit and parity-tested across local and XMTP paths whenever prompt builders evolve.

### 2026-02-17 — Thinking stream tokens now render inline in the TUI

- What happened: streamed `pi thinking` updates could arrive token-by-token and were appended as separate status lines, causing rapid newline spam and unreadable scroll in the bubble stream.
- Fix: TUI stream-status handling now coalesces incremental `pi thinking` chunks into one evolving inline status line; structural markers (for example code fences/tags) remain separate lines.
- Prevention: treat high-frequency streaming status deltas as progressive updates, not append-only log lines, and keep regression tests for token-chunk and cumulative snapshot flows.

### 2026-02-17 — Inference now splits fast Type1 vs deep Type2, logs pi command failures, and seeds model guide

- What happened: model plan/defaults could show medium thinking for both Type1 and Type2, pi invocation failures often collapsed into generic fallback messaging, and fresh workspaces lacked a baseline model tuning reference.
- Fix: inference defaults now enforce Type1=`minimal` and Type2=`xhigh`; local/XMTP chat attempts auto-repair and retry before fallback; command-level inference failures now append provider/command/stdout/stderr diagnostics to `.tako/logs/error.log`; workspace templates now ship `resources/model-guide.md`.
- Prevention: keep thinking-profile defaults explicit per cognition lane, persist full subprocess diagnostics for every inference command failure, and ship operator-facing tuning guidance with first-run templates.

### 2026-02-17 — Explore completion copy now follows stage/mood persona

- What happened: `/explore` completion messages always used the fixed prefix "I just learned something exciting," which felt canned regardless of stage or mood.
- Fix: replaced the hardcoded insight/mission prefixes with life-stage + DOSE-label aware phrasing and threaded stage/tone/mood state into explore completion formatting.
- Prevention: keep operator-facing narrative copy generated from persona state (stage + tone + mood) rather than static one-size-fits-all strings.

### 2026-02-17 — Idle boredom now drives exploration and pi turns are log-visible

- What happened: long idle stretches could feel like Tako was "doing nothing," and pi-backed chat turns were hard to audit from logs during extended runs.
- Fix: runtime now emits boredom signals during idle periods, triggers boredom-driven exploration on a bounded cadence, and emits novelty events that reinforce DOSE; pi chat now writes concise user/assistant turn summaries to both app and daemon logs.
- Prevention: keep autonomy loops tied to explicit event signals (boredom/novelty) and preserve operator observability by logging provider-specific turn summaries for long-running inference sessions.

### 2026-02-16 — TUI shutdown no longer crashes on activity markup parsing

- What happened: during app shutdown, activity-panel rendering could raise `textual.markup.MarkupError` when activity strings contained markup-like tokens (for example bracketed provider names), which crashed the session.
- Fix: sidebar/status `Static` widgets now render with `markup=False`, and activity lines are escaped before rendering so queued worker errors cannot trip Rich markup parsing.
- Prevention: keep operator/runtime-generated text treated as plain text in TUI status panels and cover markup-containing activity entries with a dedicated unit test.

### 2026-02-16 — Pi chat now runs with full tool/skill access

- What happened: operator chat could answer as if live web/tooling access was unavailable because pi inference was launched with `--no-tools --no-extensions --no-skills` and starter capabilities could remain disabled.
- Fix: pi inference now keeps tools/extensions/skills enabled, workspace `skills/` and `tools/` are linked into pi runtime context, starter skills include both `skill-creator` and `tool-creator`, and installed extensions are auto-enabled for operator-approved autonomy.
- Prevention: keep inference execution flags, extension enable defaults, and starter-capability docs/tests aligned so runtime behavior matches operator expectations.

### 2026-02-16 — Operator-requested purpose edits now apply directly in chat

- What happened: operator natural-language requests to fix Takobot purpose text could be refused with a hard-boundary message, even when the request came from the operator.
- Fix: local and XMTP operator chat flows now treat purpose/mission edit requests as authorized updates, patch `SOUL.md` directly, and ask only for missing replacement wording when needed.
- Prevention: keep boundary prompts explicit that only non-operator edits are blocked and cover natural-language operator identity/config update paths with dedicated parser tests.

### 2026-02-16 — Child-stage chat is now context-first (not task-first)

- What happened: child-stage conversations could feel like immediate planning/interrogation instead of gentle operator context discovery.
- Fix: child-stage chat prompts now prioritize small, simple context questions (who/where/what they do), capture operator notes in `memory/people/operator.md`, and add operator-shared websites to `[world_watch].sites` for monitoring.
- Prevention: keep child-stage behavior explicitly encoded in prompt policy + operator-profile capture routines/tests so later prompt changes do not regress into task-first interactions.

### 2026-02-16 — Child stage now runs random curiosity crawls

- What happened: child-stage world learning relied mostly on configured RSS feeds, so proactive discovery could miss novel signals and felt less researcher-like.
- Fix: added a child-stage `CuriositySensor` that randomly explores Reddit/Hacker News/Wikipedia, writes deduped world items, and emits mission-linked questions into notes/briefings.
- Prevention: keep child-stage exploration behavior explicitly encoded in runtime sensor wiring + tests (`sensor`, `runtime notebook`, and `stage policy` coverage) so future refactors do not remove spontaneous question generation.

### 2026-02-16 — Memory frontmatter + life stages now drive runtime behavior

- What happened: memory placement rules were implicit, and onboarding/cadence did not follow explicit life stages.
- Fix: `MEMORY.md` is now an explicit memory-system frontmatter spec, memory markdown is constrained to `memory/**`, and lifecycle policy (`[life].stage`) now controls onboarding order, world-watch cadence, Type2 daily budget, DOSE baseline multipliers, and stage-specific ASCII octopus rendering.
- Prevention: keep stage policy and memory boundaries encoded in config/runtime/docs/tests together; log stage transitions in daily notes whenever policy changes.

### 2026-02-16 — Deployment now installs `tako.sh` and pi login is operator-assisted

- What happened: package installs did not guarantee `tako.sh` was installed, and pi auth onboarding relied mostly on passive token discovery without an explicit assisted login flow.
- Fix: packaging now includes `tako.sh` as an installed script, the wrapper supports deployed-mode dispatch, and `inference login` now runs an operator-assisted pi login relay with prompt/answer handling while still auto-importing Codex OAuth into workspace pi auth.
- Prevention: keep shell-wrapper packaging under test (`pyproject.toml` + `MANIFEST.in`) and keep interactive auth workflows explicit in both TUI command surface and inference runtime helpers.

### 2026-02-16 — EventBus replaced JSONL queue polling

- What happened: runtime cognition was writing events to `.tako/state/events.jsonl` and separately polling that file as a queue, which added latency and duplicate moving parts.
- Fix: introduced an in-memory `EventBus` that appends JSONL for audit and dispatches events directly to subscribers/Type1 queue; removed the JSONL ingest loop.
- Prevention: keep event transport single-path (publish once, fan out in memory) and reserve JSONL for replay/audit only.

### 2026-02-16 — World Watch + briefings made research visible

- What happened: Tako had no first-class world sensor, no durable world notebook stream, and no bounded proactive briefing routine tied to mission context.
- Fix: added `RSSSensor` (feed polling + dedupe), deterministic `memory/world/YYYY-MM-DD.md` note writes, bounded runtime briefings with persisted state, and daily Mission Review Lite snapshots.
- Prevention: treat sensing, note-taking, and proactive summaries as explicit runtime services with persisted cadence/state files under `.tako/state/`.

### 2026-02-16 — Pi runtime is now required for all inference

- What happened: multi-provider fallback could mask missing pi runtime and drifted from the desired local-first agent setup.
- Fix: inference now enforces pi-only execution, runtime discovery auto-installs workspace-local nvm/node + pi packages when missing, and local-system API keys are adopted for pi when available.
- Prevention: keep inference policy explicit in app/CLI/docs/tests and ensure workspace-local runtime bootstrapping remains automatic and observable.

### 2026-02-16 — Live research task visibility in TUI

- What happened: during long research turns, operators could see the stream spinner but not concrete current work (for example web browsing/search/tool activity).
- Fix: inference stream tool events are now parsed into task updates and surfaced in the TUI as `active work` in the Tasks panel; local `web`/`run` commands also update active-work state.
- Prevention: whenever streamed inference/tooling behavior changes, keep operator-facing progress telemetry explicit in Tasks/Activity panels and test task-event parsing.

### 2026-02-16 — XMTP replies mirrored in TUI + mission objectives formalized

- What happened: remote XMTP replies were not visible in the local TUI transcript, and mission/objective notes captured during onboarding were loosely stored and could feel non-durable.
- Fix: daemon outbound XMTP sends now emit app hooks so replies appear in the TUI transcript/activity feed; mission objectives are now persisted as a formal `## Mission Objectives` section in `SOUL.md` with local `mission show|set|add|clear` controls.
- Prevention: keep operator-facing state in canonical git-tracked docs (`SOUL.md`) and mirror remote conversation I/O into local observability surfaces.

### 2026-02-16 — TUI input queue prevents local chat stalls

- What happened: while a long inference turn was active, terminal input handling could feel blocked because submissions awaited routing inline.
- Fix: moved local input handling to a dedicated queue + worker so new messages can be entered immediately while previous turns are still running.
- Prevention: keep UI submission path non-blocking; do long-running routing/inference work in background workers and expose queue depth in UI status.

### 2026-02-16 — Terminal retains full operator control after pairing

- What happened: terminal fallback/chat copy implied that identity/config/tools/permissions/routines changes were XMTP-only once paired, which confused operator expectations.
- Fix: clarified runtime behavior so the terminal app remains a full operator control surface even when XMTP is paired, and updated prompt/fallback copy to match.
- Prevention: keep control-plane language consistent across fallback text, model prompts, and docs whenever pairing behavior changes.

### 2026-02-16 — Canonical identity name enforced in chat prompts

- What happened: after identity rename, model chat prompts still hard-coded “You are Tako,” causing self-introduction drift despite persisted identity state.
- Fix: local and XMTP chat prompt builders now inject canonical identity name from workspace/identity state and explicitly instruct the model to self-identify only with that name.
- Prevention: avoid hard-coded identity tokens in prompt templates; route all naming through canonical identity helpers tied to config/state.

### 2026-02-15 — XMTP resilience + terminal-native right-click copy

- What happened: operators observed XMTP reliability issues and right-click copy in the TUI could clear selection instead of copying selected text.
- Fix: added XMTP send retries and daemon-side client rebuild on repeated stream/poll failures; added explicit in-app right-click copy for selected transcript/stream text so selection is preserved and copied reliably.
- Prevention: keep transport resilience in daemon loops and provide deterministic clipboard actions for transcript inspection inside the TUI.

### 2026-02-15 — Inference stall visibility + bounded chat timeout

- What happened: local inference turns could appear stuck on “responding” for long periods with little telemetry, especially during multi-provider fallback attempts.
- Fix: added richer inference debug status lines (ready providers, periodic watchdog updates), app-log tracing for provider/status transitions, and a global local-chat timeout budget to prevent indefinite stalls.
- Prevention: keep fallback attempts time-bounded and emit continuous operator-visible debug telemetry for long-running inference turns.

### 2026-02-15 — Bubble stream now exposes request focus during long thinking

- What happened: during long inference turns, the UI could show “responding” without clear visibility into what request was being worked.
- Fix: bubble stream now shows a concise focus line (from current user request), elapsed thinking/responding time, and a waiting status when tokens are delayed.
- Prevention: keep long-running inference UX explicit by surfacing active objective context directly in the stream panel.

### 2026-02-15 — TUI tab completion for commands

- What happened: command typing in the TUI was still manual after slash dropdown discovery, slowing frequent operator command entry.
- Fix: added `Tab` autocomplete in the input box for command names (plain and slash-prefixed) with candidate cycling on repeated `Tab`.
- Prevention: keep high-frequency command entry ergonomic and test helper logic for completion context + candidate matching.

### 2026-02-15 — Slash command discovery moved into in-input dropdown

- What happened: slash command discovery was shown in the transcript/system output area, which added noise during normal chat.
- Fix: moved slash discovery into a dedicated dropdown panel under the input field, driven by prefix matching while typing `/...`.
- Prevention: keep command discovery UI state in dedicated widgets and avoid writing suggestion lists into conversation logs.

### 2026-02-15 — TUI slash command discovery + quick runtime controls

- What happened: operators wanted faster in-app command discovery and direct shortcuts for model inspection, updates, runtime stats, and DOSE tuning.
- Fix: added slash-command discovery (`/` opens an in-input dropdown with command shortcuts), added `/models`, `/stats`, and `/upgrade` command paths, and extended `dose` command parsing to accept direct level setting (`dose <channel> <0..1>`).
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
