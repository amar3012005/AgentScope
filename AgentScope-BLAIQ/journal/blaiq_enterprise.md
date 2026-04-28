# BLAIQ Enterprise: The Multi-User Agentic Platform

## Vision
To build a world-class, multi-user enterprise platform that rivals **MANUS** and **KIMI** in complexity and robustness. By leveraging the **AgentScope Runtime**, BLAIQ provides a seamless, "Always-On" workstation where thousands of users can run custom, high-fidelity agentic workflows simultaneously.

## Strategic Pillars

### 1. Massive Scale via AaaS (The Data Plane)
*   **Concept**: Every agent is a standalone micro-service.
*   **Platform Equivalent**: Similar to how KIMI or MANUS scale their backend, BLAIQ uses **Agent-as-Service** containers. 
*   **Scale**: We can spawn 100 `DeepResearch` containers to handle a surge in enterprise research requests without affecting the core UI.

### 2. Perpetual Memory & Multi-User State
*   **Concept**: Use **RedisSession** and HIVE-MIND to provide persistent, user-aware memory.
*   **Benefit**: A user can start a complex 7-stage mission on their laptop, walk away, and resume it on their mobile device exactly where the "Research" agent left off. State is never lost.

### 3. Dynamic Planning (The Strategic Architect)
*   **Concept**: Moving from static templates to a **Re-Act Planner**.
*   **Capability**: Like MANUS, the BLAIQ Strategist doesn't just "follow instructions"—it **reasons** about the goal, discovers the best agents for the job, and constructs a bespoke DAG (Directed Acyclic Graph) for that specific user's problem.

### 4. Enterprise-Grade Security (Sandboxing)
*   **Concept**: **Sandboxed Tool Execution** for all agents.
*   **Value**: Enterprises can safely allow agents to generate code, run data analysis, or render complex visuals because every tool call is isolated. This is a critical requirement for production deployment in corporate environments.

### 5. Seamless Workstation UX
*   **Concept**: Real-time streaming via **SSE** and the **Yielding Bridge**.
*   **User Experience**: Users see the agents "thinking" and "writing" in real-time. This eliminates the "black box" feeling and builds trust in the agentic output.

## Competitive Comparison

| Feature | Legacy BLAIQ | BLAIQ Enterprise (AgentScope) | Competitor (MANUS/KIMI) |
| :--- | :--- | :--- | :--- |
| **Architecture** | Monolith | **AaaS Distributed Cluster** | Distributed |
| **Persistence** | Session-only | **Multi-User Redis Rehydration** | Full Persistence |
| **Planning** | Static Routing | **Dynamic Re-Act Planner** | Autonomous |
| **Safety** | Host-level | **Docker/WASM Sandboxing** | Proprietary Sandbox |
| **Latency** | Medium | **SSE Streaming (Yielding)** | High Performance |

## Implementation Roadmap
1.  **[COMPLETED]** V2 AaaS Infrastructure (Docker + AgentScope Runtime).
2.  **[COMPLETED]** Strategist V2 (Dynamic Planning Node).
3.  **[IN PROGRESS]** Research V2 (Distributed Evidence Node).
4.  **[NEXT]** Content & Visual V2 (Sandboxed Generation Nodes).
5.  **[NEXT]** Multi-User Identity & Resource Quotas.
