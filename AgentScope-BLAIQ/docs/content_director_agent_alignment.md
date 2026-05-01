# ContentDirector Agent Alignment

## Goal

Define `ContentDirector` as an AgentScope AaaS orchestration service that stays close to the official runtime model:

- `AgentApp` as the service boundary
- `@app.query(framework="agentscope")` as the request entrypoint
- `Toolkit` for skills and tools
- hooks for observability and message tagging
- `stream_printing_messages(...)` for streaming responses

The agent should behave like a deterministic orchestration layer only where policy is required, not as a monolithic controller that re-implements framework behavior.

## Intended Role

`ContentDirector` is the visual planning agent.

It should:

- select a registered skill
- map evidence into a structured content plan
- enrich that plan with recall results
- emit a render plan for downstream execution

It should not:

- decide final rendering technology
- perform image-generation execution
- rewrite the downstream render contract
- hide orchestration policy inside fragile fallback logic

## Official-Style Shape

The closest AgentScope AaaS shape for `ContentDirector` is:

1. `AgentApp` exposes the service.
2. `Toolkit` registers skill-discovery and skill-reading tools.
3. A selector agent chooses among registered skills using structured output.
4. A planning agent turns evidence into a schema-bound abstract.
5. Hooks tag and observe the generated messages.
6. The final output is a strict render plan contract for `VanGogh`.

## What Should Stay

- `AgentApp` service wrapper
- `@app.query(framework="agentscope")`
- `stream_printing_messages(...)`
- `Toolkit`-based skill exposure
- `register_instance_hook(...)` for logging and message tagging
- multi-step planning if each step is contract-driven

## What Should Be Simplified

- Replace heuristic selector fallback scoring with structured selection whenever possible.
- Replace markdown-shaped intermediate state with explicit Pydantic or JSON contracts.
- Keep phase boundaries strict:
  - phase 0: choose skill
  - phase 1: produce abstract
  - phase 2: produce render plan
- Keep poster handling as a variant of the render plan, not a separate hidden orchestration universe.

## What Should Be Removed

- Hardcoded skill preferences
- fallback logic that infers behavior from ambiguous text when a schema exists
- duplicated prompt logic that repeats the same brand instructions in multiple places
- compatibility code that exists only to satisfy old output shapes
- any rendering-side responsibility that belongs to `VanGogh`

## Cleanup Plan

1. Introduce a single `ContentPlan` schema for phase 1 and phase 2.
2. Make skill selection return a structured `selected_skill` and `reason`.
3. Make recall enrichment operate on section IDs only.
4. Make poster output a first-class variant of the render plan.
5. Remove any implicit HTML or image execution language from `ContentDirector`.

## Alignment Criteria

`ContentDirector` is aligned when:

- the selector only chooses registered skills
- the abstract is always schema-valid
- the render plan is explicit and typed
- posters and non-posters both flow through the same orchestration contract
- no downstream rendering is attempted inside this agent

