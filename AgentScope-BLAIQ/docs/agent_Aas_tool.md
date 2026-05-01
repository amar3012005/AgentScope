The least blast-radius path is:

Keep the current sequential orchestration intact, and change only the worker invocation boundary.

That means do not touch:
- frontend event contracts
- `swarm_engine` phase model
- HITL/governance lifecycle
- service health/deployment topology
- most existing worker internals

Change only these layers:

1. `enterprise_fleet` as the adapter boundary
Turn the existing worker calls into explicit tool-style contracts without changing what they call underneath.
Example:
- `run_research_worker(...)`
- `run_text_buddy_worker(...)`
- `run_content_director_worker(...)`
- `run_governance_worker(...)`

At first, these can still just call the same AaaS endpoints. So behavior stays the same, but the interface becomes agent-as-tool compatible.

2. strategist worker-selection contract
Let `strategist_v2` reason over live agent descriptions and choose workers more cleanly, but keep returning the same routing JSON shape the engine already understands.

So:
- no frontend change
- no sequence engine rewrite
- no worker rewrite yet

3. local skill-selection inside workers
Start with one worker, ideally `text_buddy` or `content_director`, and make skill selection more explicit inside that worker runtime.
Do not globalize skill selection yet.
Do not move all agents at once.

4. optional wrapper runtime for custom agents only
If you want the schema-driven single-runtime model, implement it first only for custom agents.
Keep built-ins on current services until the pattern proves stable.

So the concrete least-risk rollout order is:

1. Add tool-style wrappers in AgentScope-BLAIQ/src/agentscope_blaiq/tools/enterprise_fleet.py
No behavior change, only interface cleanup.

2. Update `strategist_v2` to think in terms of those worker contracts
Still return same `nodes`/`artifact_family` plan.

3. Keep AgentScope-BLAIQ/src/agentscope_blaiq/workflows/swarm_engine.py as-is except maybe tiny adapter renames later.

4. Migrate one worker at a time behind the same interface
Start with:
- `governance`
- `text_buddy`
Then:
- `content_director`
Then:
- `research`

I would not start with `research` first, because it has the most external dependency complexity.

If you want the absolute minimum blast radius, the best first implementation is:

- keep every current service
- keep every current stream payload
- keep `swarm_engine`
- introduce tool-shaped wrappers only
- migrate just `governance` first

Why `governance` first:
- smallest contract
- deterministic input/output
- easy to validate
- low routing complexity
- minimal UX risk

So the shortest real answer is:

The least blast radius is to preserve the current sequential engine and frontend stream contract, and refactor only the worker invocation layer in `enterprise_fleet` into tool-style worker adapters, then migrate one worker at a time starting with `governance`.

If you want, I can turn that into a 3-phase refactor plan with exact files and first PR scope.Continued with Autopilot: Task not yet completeExplained the lowest-blast-radius migration path: keep the current sequential engine, frontend stream contract, and services intact, refactor only the `enterprise_fleet` worker boundary into tool-style adapters, and migrate one worker at a time starting with the smallest-contract candidate.



The least blast radius is to keep the current sequential engine, frontend event contract, and existing services exactly as they are, and only refactor the worker boundary in `enterprise_fleet` into tool-style adapters. That gives you the agent-as-tool interface without forcing a rewrite of `swarm_engine`, hooks, or UI streaming.

The safest rollout is one worker at a time, starting with the smallest, most deterministic contract such as `governance`, then `text_buddy`, then `content_director`, and only later `research`. That way you preserve the current orchestration skeleton and change only the invocation layer behind it.