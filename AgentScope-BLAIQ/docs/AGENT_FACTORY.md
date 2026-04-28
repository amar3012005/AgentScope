# BLAIQ Agent Factory & Autonomous Orchestration

## Overview
The **BLAIQ Agent Factory** is a paradigm shift in Agentic AI. It transforms the system from a collection of static, hard-coded services into an **Elastic Agent Fleet**. Instead of writing Python code and deploying Docker containers for every new role, BLAIQ can now "architect" and "spawn" specialized agents on the fly using natural language prompts.

### The "Agent-as-Tool" Concept
In this architecture, **entire agents are treated as tools**. A Master Agent (the Strategist) can invoke a `spawn_specialist_agent` tool to hire a worker, delegate a task, and receive a high-fidelity synthesis, all within a single reasoning loop.

---

## Core Components

### 1. Agent Blueprints (`data/blueprints/`)
A **Blueprint** is a JSON-based "DNA" for an agent. It defines:
- **Identity**: Name, description, and role.
- **Cognition**: System prompt and model choice (GPT-4o, Claude 3.5, Gemini, etc.).
- **Capabilities**: Specific toolsets (Web Search, Hivemind, Python Sandbox) enabled for that worker.

### 2. The Inflation Engine (`AgentFactory`)
The Factory is a universal host. It takes a JSON blueprint and "inflates" it into a live **AgentScope ReActAgent**. It handles:
- **Model Registration**: Automatically configuring LiteLLM routing.
- **Toolkit Provisioning**: Injecting enterprise-grade tools into the worker.
- **Memory Management**: Ensuring the worker has context for its specific mission.

### 3. The Blueprint Architect
The system can self-architect. By using the `/create-agent [description]` command, the **Strategist** uses its higher-order reasoning to design a professional system prompt and tool configuration, saving it as a new blueprint in the library.

---

## Usage & Commands

### `/create-agent [prompt]`
**Input**: `/create-agent 'a specialist in technical SEO audits'`
**Process**: 
1. The Architect designs a "Technical SEO Specialist" blueprint.
2. The Blueprint is validated for JSON schema correctness.
3. The Blueprint is persisted to the local library.
**Result**: A new agent is added to the fleet, ready to be "hired."

### `spawn_specialist_agent(task, blueprint)`
This is the internal tool used by the **Strategist** to delegate work.
- **Master** identifies a specialized sub-task (e.g., "Analyze this 10-K report").
- **Master** selects or generates a blueprint for a "Financial Analyst."
- **Master** spawns the worker and receives the structured analysis.

---

## Robust Capabilities

### High-Level Web Scraping
By spawning a specialist with specific "Scraping Persona" instructions, BLAIQ can handle complex DOM structures, anti-bot reasoning, and data normalization without needing a dedicated scraping microservice.

### Domain-Specific Audits
Current specialists created via Factory:
- **VerseWeaver**: A master muse for high-fidelity poetry.
- **API Designer**: An expert in REST/OpenAPI architectures.
- **CRO Auditor**: A psychological nudge specialist for pricing pages.

---

## Future Roadmap
- **Dynamic Tool Generation**: Agents that can write and register their own Python tools on the fly.
- **Peer-to-Peer Review**: Spawning "Auditor" agents to verify the output of "Worker" agents.
- **Automatic Deployment**: Moving local blueprints into Dockerized AaaS runtimes automatically.

---
*Created by the BLAIQ Autonomous Synthesis Engine.*
