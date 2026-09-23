---
summary: "Experience-driven skill generation, evaluation, reuse, and rollback"
read_when:
  - You want Tako to learn reusable procedures from operator tasks
  - You need to evaluate or recover a learned skill
title: "Self-Improvement"
---

# Self-Improvement

Tako learns procedural skills from operator conversations, evaluates candidates
against fixed tasks, and retrieves relevant active revisions in later operator
chats. Feedback from those later uses can produce the next revision. This is a
bounded improvement loop over context, not model-weight training or autonomous
rewriting of Takobot's code.

## What happens automatically

Meaningful local and paired-XMTP operator chat turns become runtime experiences.
An experience starts with outcome `unknown`: generating a reply does not prove
that the task succeeded. Short greetings and acknowledgements are skipped.
Non-operator conversations do not supply experiences or receive learned context.

After five fresh pieces of evidence, a background review can propose a structured
skill with applicability, procedure, pitfalls, and verification guidance. Reviews
reuse prior revisions and failure feedback. Candidates are stored with parent
IDs; they do not become active merely because the model wrote them.
Reviews may abstain when there is no useful procedure. Identical procedure
content is deduplicated, and each complete procedure fits within 2,000 characters.

By default, the operator requests evaluation and promotion. A promoted revision
can enter bounded, relevance-selected context for later operator replies. That
turn records which revisions were supplied, so failure feedback can deactivate
the affected revision and restore an eligible predecessor.

All experiences, candidate revisions, reports, and learning runtime state live
under `.tako/state/learning/`, outside git. The loop does not install tools,
enable executable extensions, or edit `SOUL.md` and operator permissions.

## Configuration and upgrades

Existing workspaces inherit these defaults when `[learning]` is absent. Add the
section to workspace `tako.toml` to make your choices explicit:

```toml
[learning]
enabled = true
review_every = 5
cooldown_seconds = 300
daily_call_budget = 12
max_context_chars = 2400
max_active_skills = 3
auto_promote = false
```

`daily_call_budget` covers both generation and evaluation calls and resets each
UTC day. Calls are reserved before inference, including failed or interrupted
attempts. Set it to `0` to stop learning inference calls. `enabled = false` also
stops experience capture and learned-context retrieval; inspection and rollback
remain available. These settings do not alter ordinary chat inference budgets.

`auto_promote = true` requests evaluation after generation and permits activation
only when the same fixed gates pass. It requires an operator-authored evaluation
suite. Missing tests, insufficient budget, or incomplete evaluation cannot
establish a promotable result.

## Operator controls

Enter these in the terminal app or paired operator XMTP chat, optionally prefixed
with `/`. They are chat commands, not shell subcommands.

| Command | Purpose |
| --- | --- |
| `learn status` | Inspect budget, latest result/error, and recent experience IDs. |
| `learn review` | Queue a candidate review without waiting for the turn-count threshold. Cooldown, deduplication, and budget still apply. |
| `learn list` | List revision IDs, parent IDs, names, and statuses. |
| `learn show <revision-id>` | Inspect the full revision and its evaluation report. |
| `learn feedback <experience-id> success [note]` | Record an observed successful outcome. |
| `learn feedback <experience-id> failure [note]` | Record a failure, deactivate implicated revisions, and retain the correction for future review. |
| `learn evaluate <revision-id>` | Queue comparison against its family's current active revision, or against no skill when none is active. |
| `learn promote <revision-id>` | Activate a revision only if its current evaluation satisfies the gates. |
| `learn rollback <revision-id>` | Remove that revision from use and recover an eligible predecessor. |

Reviews and evaluations run in the background. Check `learn status`, then
`learn show <revision-id>` for the outcome. Feedback identifies the experience,
not the skill; status includes recent IDs and redacted request previews to help
identify the correct turn.

## Fixed evaluations

The operator creates `.tako/state/learning/evaluations.json`. Version 1 contains
cases with `id`, `split` (`development` or `holdout`), `prompt`, `expected`, and
`check` (`exact` or `json`). Use 2–20 cases, unique IDs and prompts, and both
splits. The entire evaluation suite is excluded from candidate generation.

This small example checks response formatting and parsing. It is a schema
example, not evidence that learning improves these tasks:

```json
{
  "version": 1,
  "cases": [
    {
      "id": "parse-development",
      "split": "development",
      "prompt": "Return only a JSON object with label (string) and count (integer), parsed from: Copper | 7",
      "expected": {"label": "Copper", "count": 7},
      "check": "json"
    },
    {
      "id": "format-development",
      "split": "development",
      "prompt": "Format these values as label=count, with no other text: label Copper, count 7.",
      "expected": "Copper=7",
      "check": "exact"
    },
    {
      "id": "parse-holdout",
      "split": "holdout",
      "prompt": "Return only a JSON object with label (string) and count (integer), parsed from: Silver | -2",
      "expected": {"label": "Silver", "count": -2},
      "check": "json"
    },
    {
      "id": "format-holdout",
      "split": "holdout",
      "prompt": "Format these values as label=count, with no other text: label Silver, count -2.",
      "expected": "Silver=-2",
      "check": "exact"
    }
  ]
}
```

Each case is run with the candidate and the baseline using the same selected
model. Exact checks trim outside whitespace before comparing text; JSON checks
compare parsed values, preserving distinctions such as booleans versus numbers.
Promotion requires strict development improvement, no per-case holdout
regression, and at least one passing candidate holdout case. If the baseline
already passes every case, there is no demonstrated improvement to promote.

Reports bind the candidate body, baseline, model, and evaluation suite. Changed
inputs invalidate promotion evidence. A different model needs a new candidate
generated and evaluated with that model; incompatible active revisions are not
retrieved. Operator feedback is additional evidence, not a way to bypass the
evaluation gate.

Repeated use makes a holdout part of validation. Before relying on a claimed
improvement, test an independently chosen, previously unseen task. These checks
measure text responses; they do not test tool execution or establish general
task-success or speed gains.

## Isolation and recovery

Candidate generation and evaluation call the pi-ai SDK directly, without an
agent session, tools, extensions, workspace context files, or resource loading.
Command-based credential/configuration resolvers are rejected. Calls have a
2,048-token output limit and a 45-second deadline. If this restricted path is
unavailable, learning fails closed; there is no fallback to the ordinary agent
runner. Ordinary chat can continue when learning is unavailable. The evaluator
is fixed application code; generated skills cannot rewrite its checks or
expected answers.

For a bad learned response, record failure against the experience ID and inspect
the implicated revision. For immediate recovery, use `learn rollback <revision-id>`.
To suspend the whole loop, set `enabled = false`. Preserve runtime learning state
when backing up the workspace if you want its history after recovery; it is not
included in git commits.
`safe on` also pauses capture, retrieval, and new learning work and cancels the
background worker. An already-started model request may finish within its
bounded timeout; cancellation prevents subsequent evaluation or promotion.
`safe off` resumes learning. App shutdown cancels the worker as well.

For missing or failed evaluations, inspect the suite and remaining call budget
before retrying. A four-case comparison needs eight inference calls in addition
to candidate generation. For missing SDK modules under `.tako/pi/node`, use
`inference refresh` and the normal inference diagnostics. Learning requires the
restricted SDK path to work before it can resume.
The current provider must be pi. Learning uses an explicit Type1 model and does
not silently fall back to another model or provider. Use `models list`, then
`models type1 <provider/model>` if the configured model lacks credentials (for
example, an OpenAI API model configured when only Codex OAuth is available).

The archive retains at most 200 recent experiences and 100 distinct revisions.
When the revision archive fills, generation stops with a status message; history
is preserved rather than silently deleting ancestors. Automatic consolidation
and archive management are not implemented in this release.

See the [research notes](../../resources/self-improvement-research-2026-09-23.md)
for the video-linked papers, Hermes behavior, and the techniques adopted or
deferred.
