# SECURITY_MODEL.md — Operator Control, Extensions, and Default-Deny

## Operator Imprint

- Tako is **operator-imprinted**: only the operator can change identity/config/tools/permissions/routines.
- The operator channel is established via XMTP imprinting and is stored in `.tako/operator.json` (runtime-only).
- Non-operator chats may converse and propose work, but must not cause risky actions without operator approval.

## Secrets and State

- No secrets in git. Keys and local DBs live under `.tako/` and must be ignored.
- Startup is "secretless" in the workspace: no external secrets required to boot.
- Keys are stored unencrypted on disk under `.tako/` (OS file permissions are the protection).
- If `.tako/**` is tracked by git, Tako must refuse to run.

## Multi-Instance Safety

- A workspace lock (`.tako/locks/tako.lock`) prevents running two Tako instances against the same `.tako/` state.

## Skills and Tools (Workspace Code)

Workspace code is allowed under:

- `tools/<name>/...`
- `skills/<name>/...`

Core invariant:

- **Installed != enabled**
- **Enabled != unrestricted**

### Install Pipeline (Quarantine First)

Installing from a URL never writes directly into `tools/` or `skills/`.

1. Download into `.tako/quarantine/<id>/` (no import, no execution, no setup scripts).
2. Record provenance (URL, timestamps, sha256).
3. Run static analysis:
   - detect executable code (`.py`, `.sh`, `.js`, etc)
   - scan for risky APIs (`os.system`, `subprocess`, `eval/exec`, sockets, direct file access)
   - detect sensitive path references (`.tako/`, `.ssh/`, `$HOME`, env access)
4. Compare requested permissions vs workspace defaults (`tako.toml`).
5. Produce a risk rating (Low/Medium/High) and a recommendation.

### Operator Approval Gate

- Operator chooses: install (disabled), install+enable, or reject.
- If not operator: only quarantine download + request operator review.

### Integrity on Enable

On enable:

- Re-run analysis quickly.
- Verify file hashes match what was installed.
- Refuse enablement if files changed since install until re-reviewed.

## Default-Deny

- New code is disabled by default.
- Default permissions are deny-all unless explicitly granted by the operator.
- Permission checks must be enforced at execution time (network/shell/xmtp/files).

