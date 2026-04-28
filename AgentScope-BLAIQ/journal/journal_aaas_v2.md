# BLAIQ AaaS Transition Journal (v2.2 Detailed Edition)

## Objective
Transform the BLAIQ Mission Workstation into a production-grade, distributed "Agent-as-Service" (AaaS) platform using the **AgentScope Runtime**.

## Core Architectural Decisions

### 1. Decentralized Execution (AaaS)
*   **Decision**: Move from a monolithic backend to independent agent services.
*   **Implementation**: Each core agent (Strategist, Research, etc.) is now a standalone FastAPI service using `agentscope_runtime.engine.app.AgentApp`. This allows for independent scaling and failure isolation.
*   **Reference**: [Agent as Service](file:///Users/amar/blaiq/AgentScope-casestudy/pages/deploy-and-serve/agent-as-service.md)

### 2. Autonomous Orchestration (v2.2)
*   **Decision**: Enable the Strategist to spawn and hire specialists dynamically.
*   **Implementation**: The `StrategicAgent` now utilizes a **Sequential Workflow Engine** to execute multi-agent DAGs. It manages the handoff from `Research` -> `TextBuddy` -> `ContentDirector` -> `VanGogh`.
*   **Reference**: [Workflow](file:///Users/amar/blaiq/AgentScope-casestudy/pages/building-blocks/workflow.md)

### 3. Persistent State (Redis)
*   **Decision**: Use Redis for session rehydration to handle long-running workflows and HITL pauses.
*   **Implementation**: Created `RedisStateStore` with Pydantic-backed `WorkflowRedisState` models. This enables "Mission Resumption" if a service restarts.

### 4. Real-time Command Center (TUI)
*   **Decision**: Build a high-fidelity terminal interface for stack monitoring and mission execution.
*   **Implementation**: The `tui.py` (BLAIQ Command Center) provides real-time progress bars, fleet status checks, and direct pipeline triggering.

## Detailed File Registry (v2.2)

### 🛰️ Service Mesh Nodes (AaaS)

#### **1. Research Node (v2)**
*   **Path**: `src/agentscope_blaiq/app/services/research_v2.py`
*   **Purpose**: The "Librarian" of the fleet. Performs deep tree-search and knowledge graph retrieval.
*   **AaaS Pattern**: Implements the `agentscope_runtime.engine.app.AgentApp` wrapper with a custom `/recall` endpoint for structured evidence gathering.
*   **Key Logic**: Uses `ReActAgent` combined with `Tavily` and `Hivemind` tools.
*   **Port**: `8091` (Host: `8096`)

#### **2. Text Buddy Node (v2)**
*   **Path**: `src/agentscope_blaiq/app/services/text_buddy_v2.py`
*   **Purpose**: The "Architect of Words." Synthesizes research into creative briefs, landing page copy, and email sequences.
*   **AaaS Pattern**: Standard `AgentApp` service.
*   **Key Logic**: Utilizes **Brand DNA** injection to ensure all generated text adheres to BLAIQ's tone and style guidelines.
*   **Port**: `8092` (Host: `8097`)

#### **3. Content Director Node (v2)**
*   **Path**: `src/agentscope_blaiq/app/services/content_director_v2.py`
*   **Purpose**: The "Visual Strategist." Translates text artifacts into visual storyboards and DALL-E 3 instructions.
*   **AaaS Pattern**: `AgentApp` service.
*   **Key Logic**: Maps text entities to visual metaphors and layout specs.
*   **Port**: `8092` (Host: `8098`)

#### **4. Van Gogh Node (v2)**
*   **Path**: `src/agentscope_blaiq/app/services/van_gogh_v2.py`
*   **Purpose**: The "Rendering Engine." Generates DALL-E 3 prompts and production-ready React/Tailwind code.
*   **AaaS Pattern**: `AgentApp` service with **Bulletproof Message Extraction** logic to handle polymorphic LLM outputs.
*   **Key Logic**: Hardened against `KeyError: 'text'` by using safe `getattr` on `Msg` objects.
*   **Port**: `8092` (Host: `8099`)

#### **5. Agent Factory (v2)**
*   **Path**: `src/agentscope_blaiq/app/services/factory_v2.py`
*   **Purpose**: The "Specialist Spawner." Births new agents on-the-fly based on user prompts.
*   **AaaS Pattern**: `AgentApp` service.
*   **Key Logic**: Synchronizes agent blueprints between the Docker mesh and the host via a shared volume (`/app/data/blueprints`).
*   **Port**: `8100` (Host: `8100`)

### 📜 Mesh Contracts & Persistence

#### **1. Workflow Engine V2**
*   **Path**: `src/agentscope_blaiq/workflows/engine_v2.py`
*   **Purpose**: The "Conductor" of the sequential production pipeline.
*   **Approach**: Uses a state-machine pattern to handle multi-agent handoffs.
*   **Hardening**: Includes **StreamEvent Sequencing** to ensure the TUI displays progress in the correct order.

#### **2. Redis Persistence Layer**
*   **Path**: `src/agentscope_blaiq/persistence/redis_state.py`
*   **Purpose**: Global state synchronization.
*   **Approach**: Uses `WorkflowRedisState` (Pydantic) to store the DAG progress, allowing any node in the mesh to "know" the mission status.

#### **3. Enterprise Fleet Tooling**
*   **Path**: `src/agentscope_blaiq/tools/enterprise_fleet.py`
*   **Purpose**: The "Remote Control" for the fleet.
*   **Approach**: Wraps `httpx` RPC calls into standard AgentScope `Toolkit` functions. It handles the **Coolify Port Mapping** (Host vs Container) automatically.

## AgentScope Documentation & Concepts Leveraged

We have strictly followed the **AgentScope Case Study** and **API Documentation** to build this enterprise mesh:

1.  **[Agent as Service](file:///Users/amar/blaiq/AgentScope-casestudy/pages/deploy-and-serve/agent-as-service.md)**:
    *   Used `AgentApp` to wrap our `ReActAgent` logic.
    *   Implemented the `/query` framework for streaming responses.
2.  **[Building Blocks: Agent](file:///Users/amar/blaiq/AgentScope-casestudy/pages/building-blocks/agent.md)**:
    *   Used the `BaseAgent` and `ReActAgent` classes for consistent memory and tool-use behavior.
3.  **[Message Passing (Msg)](file:///Users/amar/blaiq/AgentScope-casestudy/pages/building-blocks/message.md)**:
    *   Adopted the standardized `Msg` dictionary format (`name`, `content`, `role`, `metadata`) for all cross-service communication.
4.  **[Tool & Toolkit](file:///Users/amar/blaiq/AgentScope-casestudy/pages/building-blocks/tool.md)**:
    *   Registered our RPC-based fleet tools into a unified `Toolkit` so the Strategist can call remote services as if they were local functions.
5.  **[Workflow & DAG](file:///Users/amar/blaiq/AgentScope-casestudy/pages/building-blocks/workflow.md)**:
    *   Applied the topological sorting principles from the Workflow section to design our Sequential Pipeline.

## Deployment Hardening (v2.2)
*   **DNS Sync**: Configured `127.0.0.11` as the primary resolver to fix `socket.gaierror`.
*   **Volume Sync**: Linked host `/data/blueprints` to container `/app/data/blueprints` for real-time agent persistence.
*   **Role Sync**: Aligned all model roles to standard `system`, `user`, `assistant` to prevent LLM rejection.
