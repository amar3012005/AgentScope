# Session Summary [2026-03-18]

- orchestrator now resolves tenant-specific `tenant_id`, `collection_name`, `qdrant_url`, `qdrant_api_key`, and Neo4j credentials via `TENANT_CONFIG_MAP_JSON` plus per-tenant env overrides, and forwards them to every sub-agent.
- GraphRAG optimized retriever accepts request-scoped Qdrant/Neo4j settings and builds specialized retrievers per tenant; Core injects the same payload when calling helpers or content agents.
- Frontends (`static/client.html`, `static/core_client.html`) now send `tenant_id`, `room_number`, `chat_history`, etc., and display agent-state timelines sourced from Core’s orchestrator stream.
- Added four repo-local skills plus `AGENTS.md` to define the standing multi-agent team for this repo and documented how to use strategist, backend, frontend, and platform roles going forward.
- Compose now includes `env_file` references plus explanation of per-tenant overrides in `.env.example`, ensuring runtime containers see the same tenant configs the strategist uses.

This summary is stored for the hivemind memory to remember our current setup and future coordination needs.
