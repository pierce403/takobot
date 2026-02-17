---
summary: "How Takobot stores chat history and builds model context"
read_when:
  - The bot forgets earlier turns
  - You are modifying chat prompt construction
title: "Conversation Context"
---

# Conversation Context

Takobot now uses OpenClaw-style session transcripts for chat context.

## Storage model

Under `.tako/state/conversations/`:

- `sessions.json` — `sessionKey -> session metadata`
- `sessions/<sessionId>.jsonl` — append-only transcript per session

Transcript entries include:

- `type: "session"` header
- `type: "message"` rows with `role`, `text`, and `created_at`

## Session keys

- Local TUI chat: `terminal:main`
- XMTP chat: `xmtp:<conversation_id_hex>`

This keeps direct sessions isolated and reproducible across restarts.

## Prompt context strategy

For each model call:

1. Load prior transcript messages for the current session.
2. Keep the last **N user turns** and associated assistant replies (default: `12` turns).
3. Apply a character budget tail trim (default: `8000` chars).
4. Load a bounded excerpt of repo-root `MEMORY.md` (memory-system frontmatter spec).
5. Load a bounded excerpt of repo-root `SOUL.md` (identity + boundaries).
6. Compute a DOSE-derived focus profile (`focused`/`balanced`/`diffuse`) per inference call.
7. Run semantic memory recall with `ragrep` over `memory/` and adapt recall breadth to focus:
   - focused: small recall set (minimal context)
   - diffuse: broad recall set (more context)
8. Inject stage-aware behavior guidance (for example child-stage answer-first tone with anti-repeat follow-up constraints).
9. Inject `SOUL.md` excerpt + memory frontmatter + focus summary + RAG memory context + formatted history block before `user_message=...`.

This mirrors OpenClaw’s “session transcript + bounded history window” pattern.

## Channel parity

Local TUI and XMTP plain-text chat now share the same core context stack (SOUL, MEMORY frontmatter, focus, RAG, and bounded conversation history) to reduce behavior drift between channels.

## What is persisted

- Plain user/assistant chat turns are persisted.
- Local commands and system diagnostics are not added to prompt history by default.
- Inference fallback replies are still stored, preserving continuity when providers fail.
