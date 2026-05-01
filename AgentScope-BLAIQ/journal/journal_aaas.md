# BLAIQ AaaS Transition Journal (v3.0 Detailed Edition)

## Recent Update: Relational Chat & Artifact Persistence (2026-04-30)

Successfully transitioned from volatile `localStorage` and complex execution-log-based state to a production-grade relational persistence layer in PostgreSQL.

### 1. Unified Message Persistence
*   **Goal**: Ensure chat conversations, artifacts, and final responses are persistent across multiple user sessions and devices.
*   **Implementation**: Created `ConversationRecord` and `ConversationMessageRecord` models in SQLAlchemy.
*   **Workflow Integration**: The `SwarmWorkflowEngine` now synchronously saves the user's initial query and the swarm's final response to the database, linked by `thread_id`.

### 2. Side-car Telemetry & Artifact Mapping
*   **Decision**: Decouple technical "thoughts" (telemetry) from "public" chat history.
*   **Mechanism**: The database stores the clean chat interaction, while the `thread_id` acts as a side-car key to fetch high-fidelity artifacts (React code, Storyboards) from the server-side artifact store.

### 3. Frontend Global State Refactor
*   **Implementation**: Refactored `BlaiqWorkspaceProvider` to fetch history from `/api/v1/conversations` on mount.
*   **UX**: The sidebar now populates with historical sessions dynamically loaded from the existing PostgreSQL container, eliminating data loss on browser refresh.

## Recent Feature: Poster Path & Visual Synthesis v2.0 (2026-05-01)

Transitioned the visual generation pipeline from generic HTML mockups to high-fidelity, brand-aligned image generation for Poster artifacts.

### 1. Deterministic Poster Feature Path
*   **Goal**: Ensure posters are generated with maximum brand density and specific visual constraints, bypassing generic synthesis.
*   **Implementation**: Added `_is_poster_feature_path` to `ContentDirectorV2` to detect poster-related intents.
*   **Mechanism**: If a poster is requested, the service spawns a `ContentDirectorPosterFeature` agent. This agent fuses **Brand DNA**, **Brand Tone**, and **Template Skills** into a sub-1000-token "Image Generation Prompt".
*   **Output**: A structured markdown brief containing the core image prompt, negative prompt, and brand translation directives.

### 2. VanGogh "Dumb" Pipeline (Direct Tooling)
*   **Logic**: Refactored `VanGoghV2` to act as a direct execution engine for visual plans.
*   **Tooling**: Registered `generate_image` and `generate_video` tools (OpenRouter/LiteLLM).
*   **Trigger**: If the incoming `visual_render_plan_v1` specifies `render_mode: "generate_image"`, VanGogh bypasses LLM reasoning and immediately executes the tool call with the provided prompt.

### 3. Frontend Intent Extraction
*   **Path**: `blaiq-workspace-context.jsx`
*   **Fix**: Replaced hardcoded `visual_html` hinting with `extractArtifactTypeFromContent`. The frontend now dynamically identifies if the user wants a `poster`, `one_pager`, or `presentation`, and informs the backend accordingly.

### 4. Infrastructure & Key Management
*   **Propagation**: Updated `docker-compose.coolify.yml` to inject `OPENROUTER_API_KEY` into the `van-gogh-service` environment.
*   **Persistence**: Verified that the root `.env` is correctly loaded by services via the `env_file` directive in Compose.

## Objective
Transform the BLAIQ Mission Workstation into a production-grade, distributed "Agent-as-Service" (AaaS) platform using the **AgentScope Runtime**.

## Core Architectural Decisions

### 1. Decentralized Execution (AaaS)
*   **Decision**: Move from a monolithic backend to independent agent services.
*   **Implementation**: Each core agent (Strategist, Research, etc.) is now a standalone FastAPI service using `agentscope_runtime.engine.app.AgentApp`. This allows for independent scaling and failure isolation.
*   **Reference**: [Agent as Service](file:///Users/amar/blaiq/AgentScope-casestudy/pages/deploy-and-serve/agent-as-service.md)

### 2. Autonomous Orchestration (v3.0)
*   **Decision**: Enable the Strategist to spawn and hire specialists dynamically with event-driven escalation.
*   **Implementation**: The `SwarmEngine` (Master) now utilizes a **Sequential Workflow Engine** with **Event-Driven Oracle Insertion**. It manages the flow (Research → [Oracle] → TextBuddy → ContentDirector → VanGogh) and monitors evidence quality to trigger HITL escalations autonomously.
*   **Reference**: [Orchestration](file:///Users/amar/blaiq/AgentScope-casestudy/pages/building-blocks/orchestration.md)

### 3. Persistent State (Redis)
*   **Decision**: Use Redis for session rehydration and research-first policy enforcement.
*   **Implementation**: Created `RedisStateStore` with `SwarmSuspendedState` (Pydantic) for task resumption. A `research_done` guard ensures the fleet adheres to the search-before-ask policy.

### 4. Real-time Command Center (TUI)
*   **Decision**: Build a high-fidelity terminal interface for stack monitoring and mission execution.
*   **Implementation**: The `tui.py` provides real-time progress bars, event-driven status updates, and direct sequential pipeline triggering via `/pipeline`.

## Detailed File Registry (v3.0)

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

#### **1. Swarm Engine (v3)**
*   **Path**: `src/agentscope_blaiq/workflows/swarm_engine.py`
*   **Purpose**: The "Orchestrator" of the multi-agent fleet.
*   **Update (v3)**: Implemented **Event-Driven Oracle Escalation**.
*   **Key Logic**: The engine now monitors research fidelity via `_should_fire_oracle()`. If evidence is insufficient, it dynamically inserts the Oracle node into the sequence to resolve ambiguities with the human user before proceeding to content synthesis.
*   **AgentScope Alignment**: Follows the **Master-Worker Pattern** where the coordinator (Master) makes routing decisions based on worker feedback.

#### **2. Redis Persistence Layer**
*   **Path**: `src/agentscope_blaiq/persistence/redis_state.py`
*   **Purpose**: Global state synchronization and HITL flow management.
*   **Approach**: Uses `SwarmSuspendedState` (Pydantic) to store the DAG progress, allowing the TUI to resume missions after human input.

#### **3. Enterprise Fleet Tooling**
*   **Path**: `src/agentscope_blaiq/tools/enterprise_fleet.py`
*   **Purpose**: The "Remote Control" for the fleet.
*   **Approach**: Wraps `httpx` RPC calls into standard AgentScope `Toolkit` functions. It handles the **Coolify Port Mapping** and enforces a **Research-First Policy** via Redis-backed guards.

## Strategic Cleanup (2026-04-28)
*   **Folder Archival**: To eliminate developer confusion between the AaaS services and legacy local agents, all directories under `src/agentscope_blaiq/agents/` (except `backup/`) were moved to `src/agentscope_blaiq/agents/backup/`.
*   **Git Purge**: Successfully removed 250MB+ of legacy `node_modules` and binary bloat from git history via `git filter-repo`, reducing push times from minutes to seconds.
*   **Active Runtime**: The system now explicitly runs via the AaaS mesh defined in `src/agentscope_blaiq/app/services/` and orchestrated via `swarm_engine.py`.

## Update: Dynamic Lifecycle Implementation (2026-04-28)

Implemented end-to-end dynamic creation of skills and agents via the TUI Command Center.

### 1. Natural Language Skill Creation (`/new-skill`)
*   **Workflow**: User provides a prompt → Strategist AaaS service generates a structured `SKILL.md` → TUI writes it to `src/agentscope_blaiq/skills/<name>/` → `Toolkit` registers it immediately.
*   **Impact**: New behaviors (e.g., Twitter threads, LinkedIn posts) can be added without modifying source code or restarting services.
*   **Technical Detail**: The `Toolkit.register_agent_skill(path)` method was corrected to avoid invalid `register_middleware` calls.

### 2. Genetic Agent Spawning (`/create`)
*   **Workflow**: User provides a persona description → Factory AaaS service architecturally designs a JSON blueprint → Blueprint is stored in `data/blueprints/` → A shadow `SKILL.md` is created to notify the Strategist of the new specialist's existence.
*   **Visibility**: Newly created agents are tracked in `workspace.engaged_agents` and listed in the `/list` command as **ACTIVE**.

### 3. Service Mesh Hardening
*   **RPC Synchronization**: Standardized all internal fleet communication on `localhost` port mapping (8091-8100) to ensure the TUI can control Docker containers during development.
*   **Error Resilience**: Hardened `safe_text_extract` to handle diverse message types (Markdown, JSON, raw strings) and added `httpx` timeout handling for long-running architecture tasks.

## StrategistV2 Refactor (2026-04-28)
*   **Problem**: The original StrategistV2 was a "Planner that gives up" — a ReActAgent with a 40+ line bloated system prompt that attempted orchestration via tool calls but never actually executed the pipeline. The handoff to `WorkflowEngineV2` was commented out.
*   **Solution**: Refactored to use AgentScope's **Master-Worker Pattern** with:
    *   **Structured Output**: `MissionPlanOutput` (Pydantic) produces schema-validated mission plans instead of improvised text
    *   **Evidence Quality Evaluation**: `EvidenceEvaluator` class detects insufficient research results and triggers Oracle escalation autonomously
    *   **Direct Handoff**: Uncommented and implemented the bridge from Strategist → `WorkflowEngineV2` execution
    *   **Minimal System Prompt**: Reduced from 40+ lines to 3 lines — orchestration logic is now handled by `structured_model` and framework patterns, not prompt engineering
*   **Legacy**: Original file moved to `strategist_v2_legacy.py` for reference

## AgentScope Documentation & Concepts Leveraged

We have strictly followed the **AgentScope Case Study** and **API Documentation** to build this enterprise mesh:

1.  **[Agent as Service](file:///Users/amar/blaiq/AgentScope-casestudy/pages/deploy-and-serve/agent-as-service.md)**:
    *   Used `AgentApp` to wrap our `ReActAgent` logic.
2.  **[Building Blocks: Agent](file:///Users/amar/blaiq/AgentScope-casestudy/pages/building-blocks/agent.md)**:
    *   Used the `BaseAgent` and `ReActAgent` classes for consistent memory and tool-use behavior.
3.  **[Message Passing (Msg)](file:///Users/amar/blaiq/AgentScope-casestudy/pages/building-blocks/message.md)**:
    *   Adopted the standardized `Msg` dictionary format (`name`, `content`, `role`, `metadata`) for all cross-service communication.
4.  **[Tool & Toolkit](file:///Users/amar/blaiq/AgentScope-casestudy/pages/building-blocks/tool.md)**:
    *   Registered our RPC-based fleet tools into a unified `Toolkit` so the Strategist can call remote services as if they were local functions.
5.  **[Workflow & DAG](file:///Users/amar/blaiq/AgentScope-casestudy/pages/building-blocks/workflow.md)**:
    *   Applied the topological sorting principles from the Workflow section to design our Sequential Pipeline.
6.  **[Master-Worker Pattern](file:///Users/amar/blaiq/AgentScope-casestudy/pages/building-blocks/orchestration.md#master-worker-pattern)**:
    *   Implemented `SwarmEngine` as the Master coordinator and `ServiceProxyAgents` as Workers.

## Deployment Hardening (v3.0)
*   **Event-Driven HITL**: Oracle fires only when necessary, preventing redundant human interruptions.
*   **Research-First Policy**: Enforced via Redis guards in the `BlaiqEnterpriseFleet` toolkit.
*   **DNS Sync**: Configured `127.0.0.11` as the primary resolver to fix `socket.gaierror`.
*   **Volume Sync**: Linked host `/data/blueprints` to container `/app/data/blueprints` for real-time agent persistence.
*   **Role Sync**: Aligned all model roles to standard `system`, `user`, `assistant` to prevent LLM rejection.

## Universal Observability & Telemetry Hardening (2026-04-30)

Implemented a core architectural refactor to ensure universal "acting" visibility across the entire hybrid swarm, eliminating the need for redundant status reporting code in individual services.

### 1. BaseAgent Hook Injection
*   **Implementation**: Added `_universal_acting_hook` to the core `BaseAgent` class in `src/agentscope_blaiq/runtime/agent_base.py`.
*   **Mechanism**: Leverages AgentScope's `register_instance_hook` with the `pre_acting` event type. This ensures that whenever a `ReActAgent` begins a step (tool call or reasoning), it automatically emits a structured `status: acting` signal.
*   **Impact**: Absolute consistency in telemetry. Every agent in the BLAIQ fleet now automatically reports its "Thinking/Acting" state to the frontend without manual logging calls.

### 2. Full Service Fleet Refactor
*   **Cleanup**: Successfully refactored all AaaS nodes (`StrategistV2`, `DeepResearchV2`, `TextBuddyV2`, `ContentDirectorV2`, `VanGoghV2`, `GovernanceV2`, `OracleV2`) to inherit strictly from the updated `BaseAgent`.
*   **Portability**: Replaced direct `ReActAgent` instantiation with the factory method `_create_runtime_agent()`, ensuring telemetry injection is consistent across all specialized services.

### 3. Frontend Telemetry & UI Response
*   **Zustand Tracking**: Updated `agent-store.js` and `blaiq-workspace-context.jsx` to synchronize the agent's `status` (idle, active, acting, completed) in real-time.
*   **Visual Fidelity**: Enhanced `AgentActivityStack.jsx` with an "Acting" badge and amber-pulsing animation to provide immediate visual feedback during long-running tool executions.
*   **UX Utility**: Integrated a copy-to-clipboard symbol for message bubbles to streamline user workflow.
