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
4. Inject the formatted history block into the inference prompt before `user_message=...`.

This mirrors OpenClaw’s “session transcript + bounded history window” pattern.

## What is persisted

- Plain user/assistant chat turns are persisted.
- Local commands and system diagnostics are not added to prompt history by default.
- Inference fallback replies are still stored, preserving continuity when providers fail.
