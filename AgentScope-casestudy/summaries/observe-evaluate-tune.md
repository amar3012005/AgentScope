# observe-evaluate-tune

This note groups the docs that help you see agent behavior, measure quality, and improve it.

## Covered docs

- [Observability](https://docs.agentscope.io/observe-and-evaluate/observability)
- [Evaluation](https://docs.agentscope.io/observe-and-evaluate/evaluation)
- [AgentScope Studio](https://docs.agentscope.io/observe-and-evaluate/observability)
- [Tuning overview](https://docs.agentscope.io/tune-agent/tune-your-first-agent)
- [Prompt tuning](https://docs.agentscope.io/tune-agent/prompt-tuning)
- [Model selection tuning](https://docs.agentscope.io/tune-agent/model-selection-tuning)
- [Model weights tuning](https://docs.agentscope.io/tune-agent/model-weights-tuning)
- [Multi-agent tuning](https://docs.agentscope.io/tune-agent/tune-multi-agents)

## Main themes

- Observability is built on OpenTelemetry spans, token usage tracking, and AgentScope Studio.
- Evaluation treats agents like software systems that need measurable cognitive checks.
- OpenJudge extends evaluation with LLM-based judging.
- The tuner docs cover prompt optimization, model selection, RL-based weight tuning, and multi-agent tuning.

## Practical reading order

1. Start with observability if you need to debug runs.
2. Add evaluation once you want repeatable quality gates.
3. Use tuning only after you know what behavior you want to improve.
