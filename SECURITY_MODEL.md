# SECURITY_MODEL.md — Operator Control and Extension Safety

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

Core invariants:

- **Non-operator != control-plane authority**
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

- Operator chooses: install (enabled immediately) or reject.
- If not operator: only quarantine download + request operator review.

### Integrity on Enable

On enable:

- Re-run analysis quickly.
- Verify file hashes match what was installed.
- Refuse enablement if files changed since install until re-reviewed.

## Operator-First Defaults

- Built-in starter skills are auto-enabled so Tako has immediate capability coverage.
- Operator-approved installs are enabled immediately after `install accept`.
- Permission checks must still be enforced at execution time (network/shell/xmtp/files).

## Procedural Learning

- Only operator chat contributes learning evidence or receives learned context. `learn` controls use the existing operator boundary.
- Generated procedures remain in the ignored learning archive, outside pi's automatically discovered `skills/` tree. They grant no tool or control-plane authority.
- Reflection and text replay call pi-ai directly with no agent session, tool definitions, extensions, or workspace context loading. They cannot write the evaluation suite. Command-based credential/config resolvers are refused for these calls.
- Fixed operator-authored evaluation cases, exact candidate content, and the selected model are bound to promotion reports. A model's own approval or confidence never activates a procedure.
- Learning inherits operator-configured inference credentials and uses redacted, bounded conversation excerpts. Redaction is best effort, not a guarantee that all private content is removed; storage remains runtime-only.
- These are application-level boundaries, not an OS sandbox against another process or an operator with write access to the same files.
