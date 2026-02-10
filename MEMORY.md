# MEMORY.md — Canonical Durable Memory

This is Tako’s **only** durable memory file in the repo. Keep it small, stable, and factual.

Rules:

- Do **not** put secrets here (no keys, tokens, private URLs, credentials).
- Prefer **long-lived facts** and **stable decisions** over daily activity logs.
- Put day-to-day notes in `daily/YYYY-MM-DD.md`, then promote only what should last.

## Operator Preferences (durable)

- Keep commits small; commit + push after meaningful updates.
- Keep docs and the website (`index.html`) aligned with actual behavior.
- Track feature state in `FEATURES.md` with stability + test criteria.

## Stable Decisions

- XMTP is the control plane for operator commands and status.
- Operator imprint: only the operator may change identity, tools, permissions, or routines.
- No “encrypted vaults” in the working directory; startup must not require external secrets.
- Runtime state lives under `.tako/` (ignored); daily logs live under `daily/` (committed).

## Long-lived Facts

- Project website is served from `index.html` and the repo includes `CNAME` for `tako.bot`.
- Repository: `pierce403/tako-bot` on GitHub.

