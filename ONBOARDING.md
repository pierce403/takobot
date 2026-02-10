# ONBOARDING.md — First Wake Checklist

This is the “first wake” checklist for bringing up a new Tako instance.

## Done When

- [ ] `.tako/` runtime structure exists (`locks/`, `logs/`, `state/`, `xmtp-db/`) and `.tako/keys.json` exists.
- [ ] An XMTP identity key exists locally (no external secrets required).
- [ ] Operator is imprinted (paired) and stored locally.
- [ ] Operator receives a pairing completion message over XMTP.
- [ ] `daily/YYYY-MM-DD.md` exists for today.
- [ ] `SOUL.md`, `MEMORY.md`, and `FEATURES.md` exist and are consistent with current behavior.

## Steps

1) **Initialize runtime dirs**

- Create: `.tako/locks/`, `.tako/logs/`, `.tako/state/`, `.tako/xmtp-db/`.

2) **Generate/ensure XMTP keys (local, unencrypted)**

- Create `.tako/keys.json` with `0600` permissions (best-effort).
- Do not write keys anywhere outside `.tako/`.

3) **Imprint the operator**

- Start the daemon (no operator flags, no env-var configuration):
  - `./tako.sh` (recommended)
  - or `python -m tako_bot run`
- Tako prints a `tako address` on stdout. DM that address from the account you want as operator.
- Tako replies with a pairing challenge; reply with `pair <code>` to complete pairing.
- Store operator metadata in `.tako/operator.json` (runtime-only; ignored by git).

4) **Pairing / handshake**

- Pairing happens in-chat over XMTP (challenge/response).
- The first successful pairing becomes the operator imprint.
- Re-imprinting requires an explicit operator command over XMTP (never via CLI flags).

5) **Initialize today’s daily log**

- Ensure `daily/YYYY-MM-DD.md` exists.
- Never log secrets; summarize actions and decisions.

6) **Start heartbeat (safe by default)**

- Start a heartbeat loop; sensors are disabled by default.
- Store runtime-only heartbeat/cognition state under `.tako/state/`.

7) **Emit completion summary**

- After pairing, the operator can request status via XMTP commands:
  - `help`, `status`, `doctor`

Notes:

- **No env vars, no CLI configuration** in the standard flow. Management is via the operator XMTP channel.
