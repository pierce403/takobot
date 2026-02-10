# ONBOARDING.md — First Wake Checklist

This is the “first wake” checklist for bringing up a new Tako instance.

## Done When

- [ ] `.tako/` runtime structure exists (`keys/`, `locks/`, `logs/`, `state/`, `xmtp-db/`).
- [ ] An XMTP identity key exists locally (no external secrets required).
- [ ] Operator is imprinted (paired) and stored locally.
- [ ] Operator receives an onboarding completion summary over XMTP.
- [ ] `daily/YYYY-MM-DD.md` exists for today.
- [ ] `SOUL.md`, `MEMORY.md`, and `FEATURES.md` exist and are consistent with current behavior.

## Steps

1) **Initialize runtime dirs**

- Create: `.tako/keys/`, `.tako/locks/`, `.tako/logs/`, `.tako/state/`, `.tako/xmtp-db/`.

2) **Generate/ensure XMTP keys (local, unencrypted)**

- Create a local key file under `.tako/` with `0600` permissions (best-effort).
- Do not write keys anywhere outside `.tako/`.

3) **Imprint the operator**

- Start Tako with `tako run --operator <addr|ens>`.
- Resolve ENS to an address if needed.
- Store operator metadata in `.tako/operator.json`:
  - operator address (or inbox id if used later)
  - paired timestamp
  - allowlisted controller commands (initially minimal)

4) **Pairing / handshake**

- Message the operator first over XMTP.
- Require operator confirmation before enabling any risky capabilities (tools, sensors, networked actions beyond baseline messaging).

5) **Initialize today’s daily log**

- Ensure `daily/YYYY-MM-DD.md` exists.
- Never log secrets; summarize actions and decisions.

6) **Start heartbeat (safe by default)**

- Start a heartbeat loop; sensors are disabled by default.
- Store runtime-only heartbeat/cognition state under `.tako/state/`.

7) **Emit completion summary**

- Send a short onboarding summary to the operator over XMTP:
  - operator identity
  - enabled capabilities (should start minimal)
  - where state lives
  - how to run `doctor`

