# ONBOARDING.md — First Wake Checklist

This is the “first wake” checklist for bringing up a new Tako instance.

## Done When

- [ ] `.tako/` runtime structure exists (`locks/`, `logs/`, `state/`, `xmtp-db/`) and `.tako/keys.json` exists.
- [ ] `uv` is installed for virtualenv + dependency management.
- [ ] An XMTP identity key exists locally (no external secrets required).
- [ ] Operator is imprinted (paired) and stored locally.
- [ ] Operator pairing is confirmed from terminal after receiving an outbound XMTP DM challenge.
- [ ] `memory/dailies/YYYY-MM-DD.md` exists for today.
- [ ] `SOUL.md`, `memory/MEMORY.md`, and `FEATURES.md` exist and are consistent with current behavior.

## Steps

1) **Initialize runtime dirs**

- Create: `.tako/locks/`, `.tako/logs/`, `.tako/state/`, `.tako/xmtp-db/`.

2) **Run first-wake identity prompts**

- Preferred bootstrap flow:
  - `curl -fsSL https://tako.bot/setup.sh | bash`
  - or (from an existing checkout) `./start.sh`
- `setup.sh` bootstraps into your current directory and initializes a local working branch (`local`) that tracks `origin/main`.
- `start.sh` asks conversational first-wake questions for name and purpose, then updates SOUL identity fields.
- After SOUL prompts, `start.sh` launches terminal-first bootstrap pairing (`tako bootstrap`).
- If installed, `start.sh` can optionally use one-shot local inference CLIs (`codex`, `claude`, `gemini`) to refine wording after those conversational answers.
- One-shot inference attempts allow up to 5 minutes before timing out.
- If inference CLI attempts fail, `start.sh` prints command-level diagnostics and falls back to manual prompts.
- If `uv` is missing, `start.sh` attempts a repo-local install at `.tako/bin/uv` automatically.

3) **Generate/ensure XMTP keys (local, unencrypted)**

- Create `.tako/keys.json` with `0600` permissions (best-effort).
- Do not write keys anywhere outside `.tako/`.

4) **Imprint the operator**

- Pairing is terminal-first during bootstrap (no inbound-first DM requirement).
- Tako asks for operator XMTP handle in terminal (`.eth` or `0x...`).
- Tako sends an outbound DM challenge code to that handle.
- Operator copies the code from XMTP and pastes it back into terminal.
- Tako stores operator metadata in `.tako/operator.json` (runtime-only; ignored by git).

5) **Pairing / handshake**

- Pairing confirmation is completed in terminal for first wake.
- After imprint, management moves to XMTP only (`help`, `status`, `doctor`, `reimprint`).
- Re-imprinting is still operator-only over XMTP (`reimprint CONFIRM`), then terminal bootstrap pairs the next operator.

6) **Initialize today’s daily log**

- Ensure `memory/dailies/YYYY-MM-DD.md` exists.
- Never log secrets; summarize actions and decisions.

7) **Start heartbeat (safe by default)**

- Start a heartbeat loop; sensors are disabled by default.
- Store runtime-only heartbeat/cognition state under `.tako/state/`.

8) **Emit completion summary**

- After pairing, Tako prints that terminal is read-only/logs and XMTP is the control plane.
- The operator can request status via XMTP commands:
  - `help`, `status`, `doctor`

Notes:

- **No env vars, no CLI configuration** in the standard flow. Management is via the operator XMTP channel.
