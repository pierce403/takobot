# Model Guide

This file is a practical tuning guide for Takobot inference settings.

Use it as a starting point, then tune from observed latency, quality, and cost.
Provider model catalogs change often, so verify exact model names in provider docs.

## Takobot Defaults

- Type1 (chat, triage, short transforms): fast thinking (`minimal`).
- Type2 (deeper reasoning, review/synthesis): deep thinking (`xhigh`).

Use this split unless you have a clear reason to change it.

## Provider Families (General)

### OpenAI

- Fast/general tiers: models optimized for low latency and broad assistant tasks.
- Deep/reasoning tiers: models optimized for harder multi-step reasoning.
- Code-oriented variants: usually strongest at code editing, debugging, and agentic tool use.

### Anthropic

- Haiku-tier: fastest, lowest latency.
- Sonnet-tier: balanced quality/speed.
- Opus-tier: strongest deep reasoning, typically slower and more expensive.

### Gemini (Google)

- Flash-tier: fastest and cheapest for lightweight tasks.
- Pro-tier: stronger reasoning and synthesis, slower than Flash.
- Some Gemini variants are especially strong with large context/multimodal workflows.

### Open Source / Self-hosted

- Small models (for example 7B-13B class): lowest latency, weaker reasoning depth.
- Mid models (for example 30B-ish class): stronger quality, higher latency.
- Large models (70B+ / MoE): strongest open weights reasoning, highest infra cost.
- Code-specialized open models can outperform general open models on coding tasks.

## Task-to-Model Heuristics

- Quick intent routing, short Q/A, lightweight formatting: fast tier.
- Tool-heavy workflows with many steps but low ambiguity: balanced tier.
- Contradictions, strategy, root-cause analysis, hard synthesis: deep tier.
- Code generation/refactor/debug: code-specialized model when available.

## Tuning Workflow

1. Check current plan: `models`.
2. Observe failures in `.tako/logs/error.log` and runtime/app logs.
3. If latency is too high, keep model and lower thinking first.
4. If quality is too low, raise thinking before changing model family.
5. If still weak, switch model family (general -> code-specialized or deeper tier).

## Notes for Operators

- Prefer stable defaults over constant switching.
- Tune one variable at a time (model or thinking, not both at once).
- Capture good settings in daily notes so future runs start from known-good baselines.
