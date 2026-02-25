# Summarize CLI

Built-in starter playbook derived from OpenClaw ecosystem usage signals.
Source skill: `summarize` (rank #8, downloads 17772, stars 41).

## Purpose
Summarize URLs and local files (web, PDFs, images, audio, YouTube).

## Trigger
Use when operator requests concise summaries from documents/links/media.

## Prerequisites
- A supported summarize provider key is configured.
- Operator has approved the workflow and required credentials.
- Keep secrets out of git and out of committed docs.

## Workflow
1. Confirm prerequisites and required credentials are already present.
2. Mission alignment check: proceed only if the requested action clearly supports the operator mission in `SOUL.md`.
3. Run a quick capability probe:
   - `run command -v summarize`
   - `run summarize --help`
4. Execute the requested operation with minimal scope and clear output.
5. Summarize results, errors, and next actions for the operator.

## Safety
- Respect operator-only boundaries for config/tooling changes.
- Refuse destructive actions unless explicitly approved.
- If dependencies are missing, ask for setup before proceeding.
