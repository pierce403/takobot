# Self-improvement research notes — 2026-09-23

This reading informs [Takobot's learning loop](../docs/concepts/self-improvement.md).
The implementation adapts experience into evaluated procedural context; it does
not train model weights or demonstrate open-ended recursive self-improvement.

## Video-linked reading

Starting point: [the supplied video](https://youtu.be/claxN4oxDuY) and its
user-supplied reading list. The primary sources were checked below. A video
transcript was not retrieved; these summaries describe the papers and reports
themselves.

| Primary source | Finding and implementation choice |
| --- | --- |
| [Chen, Wang, Qu: Recursive Self-Improvement in AI](https://arxiv.org/abs/2607.07663) | Survey distinguishes bounded harness refinement from open-ended RSI and discusses stronger and weaker verification signals. Record explicit outcomes; a model's confidence does not establish improvement. |
| [Zhang, Hu et al.: Darwin Gödel Machine](https://arxiv.org/abs/2505.22954) | Empirical self-modification uses candidate archives and branching lineage, with transfer evaluations. Borrow parent revisions, retained candidates, and baseline comparison. Takobot does not implement this paper's autonomous code rewriting. |
| [Novikov, Vũ et al.: AlphaEvolve](https://arxiv.org/abs/2506.13131) | Evolution relies on supplied evaluators and a cascade of inexpensive and more costly checks. Validate structure before spending inference calls on task comparisons. |
| [Wijk, Lin et al.: RE-Bench](https://arxiv.org/abs/2411.15114) | Seven research-engineering environments compare agents and human experts across time budgets. Longer runs are not themselves evidence of improvement. Bound review and evaluation cost. |
| [Wen, Qiu et al.: Automated Weak-to-Strong Researcher](https://alignment.anthropic.com/2026/automated-w2s-researcher/) | Outcome-gradable research benefits from automation, while repeated evaluations can invite reward hacking even with hidden labels. Keep expected answers out of generation; require a separate final unseen check for strong claims. |
| [Kirgis, Kapoor, Narayanan et al.: Can AI Agents Conduct Open-Ended AI Research?](https://arxiv.org/abs/2607.27191) | Two shadow evaluations identify problems with research judgment, backtracking, resource awareness, and constraint retention. Preserve failure feedback and bound repeated reviews. Richer stagnation detection remains future work. |
| [Cunningham et al.: The Economics of Recursive Self-Improvement](https://arxiv.org/abs/2609.15802) | A theoretical economic model separates narrow benchmark improvement from broad capability and models resource bottlenecks. Keep measured gains scoped to the evaluation tasks; iteration alone does not establish self-sustaining acceleration. |
| [Burtsev: Recursive Criticality of AI Self-Improvement](https://arxiv.org/abs/2609.00137) | A conditional dynamical model distinguishes throughput from recursive amplification and successor adoption. Lineage and promotion history help describe the loop. Its scenarios are not forecasts or performance guarantees. |
| [DeepMind: From AGI to ASI](https://deepmind.google/research/publications/239142/) ([paper](https://arxiv.org/abs/2606.12683)) | Conceptual analysis of scaling, new paradigms, recursion, and multi-agent systems. It supplies no universally effective harness recipe; defer extra agents until comparative evaluation justifies their cost. |
| [International AI Safety Report 2026](https://internationalaisafetyreport.org/publication/international-ai-safety-report-2026) | Evidence synthesis highlights limits of narrow or contaminated benchmarks and deployment transfer. Combine fixed evaluations with observed operator outcomes and recoverable revisions. |
| [OpenAI: Research acceleration — The view inside OpenAI](https://openai.com/index/research-acceleration-view-inside-openai/) | Observational evidence describes growing agent use and experiment throughput alongside continuing human steering. Count verified outcomes separately from generated skills, reviews, or inference calls. |
| [Grace et al.: Thousands of AI Authors on the Future of AI](https://arxiv.org/abs/2401.02843) | Expert survey with forecasting, framing, and sampling limitations. Background context only; it does not validate a particular learning algorithm. |

The choices in the second column are engineering adaptations, not claims that
Takobot reproduces those systems or their benchmark results.

## Hermes and complementary techniques

| Primary source | What we borrow or defer |
| --- | --- |
| [Hermes skills system](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills) | Hermes records nontrivial workflows, recovered failures, and user corrections as reusable skills. It loads an index before full procedures and favors targeted updates. Takobot similarly generates structured procedures and retrieves relevant active revisions. Generated candidates remain separate from installed executable extensions. |
| [Hermes background memory review](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory) | Separate post-turn review and configurable cadence/model keep learning from dominating foreground work. Takobot uses bounded review cadence and a daily inference-call allowance. |
| [Hermes curator](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator) | Usage tracking, recoverable archival, pinning, and bounded consolidation address skill sprawl. Takobot includes revision lineage and rollback; automatic consolidation and age-based archival are future work. |
| [Agentic Context Engineering (ACE)](https://arxiv.org/html/2510.04618v1) | Itemized lessons and local updates avoid losing accumulated knowledge through wholesale context rewriting. Execution feedback guides revision. The paper also reports degradation with unreliable feedback. Takobot retains separate skills and outcome evidence; it does not equate a plausible reflection with success. |
| [GEPA](https://arxiv.org/abs/2507.19457) ([implementation](https://github.com/gepa-ai/gepa)) | Trace-informed proposals and comparative evaluation motivate candidate-versus-parent testing. Full genetic/Pareto search is deferred until representative evaluation data and sufficient budgets justify it. The current implementation is not GEPA. |
| [Reflexion](https://arxiv.org/abs/2303.11366) | Verbal feedback can inform future attempts without weight updates. Operator failure feedback is retained and supplied to subsequent skill revisions. |
| [Voyager](https://voyager.minedojo.org/) | Reusable skills and execution feedback support continued learning in a bounded environment. Borrow skill reuse; defer open-ended autonomous curriculum and executable skill synthesis. |

The [separate Hermes evolution project](https://github.com/NousResearch/hermes-agent-self-evolution)
also illustrates implementation pitfalls. Historical reports describe
[optimizing wrapper instructions instead of the actual skill](https://github.com/NousResearch/hermes-agent-self-evolution/issues/38)
and [weak keyword-overlap fitness](https://github.com/NousResearch/hermes-agent-self-evolution/issues/12).
These reports motivate binding evaluation to the exact candidate and using
deterministic task checks; they do not establish that current Hermes releases
still have those defects.

## Scope of evidence

This release verifies text-response behavior with operator-authored exact/JSON
checks. It does not benchmark tool execution, end-to-end task completion, speed,
or broad generalization. A repeatedly consulted holdout becomes validation data.
Real-world improvement claims need new tasks, independent outcomes, and cost
measurement beyond the tests used to choose a revision.
