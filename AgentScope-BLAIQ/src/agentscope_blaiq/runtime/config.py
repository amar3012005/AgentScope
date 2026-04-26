from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    contract_enforcement: str = "advisory"  # "advisory" or "enforced"
    log_level: str = "INFO"
    app_host: str = "0.0.0.0"
    app_port: int = 8090
    database_url: str = "sqlite+aiosqlite:///./agentscope_blaiq.db"
    redis_url: str = "redis://localhost:6379/0"
    upload_dir: Path = Field(default=Path("./data/uploads"))
    artifact_dir: Path = Field(default=Path("./data/artifacts"))
    agent_profile_dir: Path = Field(default=Path("./data/agent_profiles"))
    brand_voice_dir: Path = Field(default=Path("./brand_voice"))
    log_dir: Path = Field(default=Path("./logs"))
    default_tenant: str = "default"
    default_source_scope: str = "web"
    default_artifact_type: str = "visual_html"
    litellm_api_base_url: str | None = None
    litellm_api_key: str | None = None
    strategic_model: str = "gemini-2.5-pro"
    routing_model: str = "gemini-2.5-flash-lite"  # fast model for binary routing decisions
    research_model: str = "gemini-2.5-pro"
    content_director_model: str = "gemini-2.5-pro"
    hitl_model: str = "vertex_ai/claude-sonnet-4-5@20250929"
    vangogh_model: str = "vertex_ai/claude-sonnet-4-5@20250929"
    governance_model: str = "gemini-2.5-pro"
    text_buddy_model: str = "vertex_ai/claude-sonnet-4-5@20250929"
    llm_fallback_model: str | None = "gemini-2.5-flash-lite"
    llm_timeout_seconds: int = 60
    llm_max_output_tokens: int = 1200
    content_director_max_output_tokens: int = 4000
    vangogh_max_output_tokens: int = 16000
    text_buddy_max_output_tokens: int = 4000
    strategic_temperature: float = 0.1
    research_temperature: float = 0.2
    hitl_temperature: float = 0.2
    vangogh_temperature: float = 0.7
    governance_temperature: float = 0.0
    text_buddy_temperature: float = 0.4
    model_reasoning_effort: str | None = None
    nebius_api_key: str | None = None
    openai_api_key: str | None = None
    openai_api_base_url: str | None = None
    groq_api_key: str | None = None
    groq_api_base_url: str | None = None
    enable_graph_agent: bool = False
    hivemind_mcp_rpc_url: str | None = None
    hivemind_api_key: str | None = None
    hivemind_enterprise_base_url: str = "https://core.hivemind.davinciai.eu:8050"
    hivemind_enterprise_api_key: str | None = None
    hivemind_enterprise_org_id: str | None = None
    hivemind_enterprise_user_id: str | None = None
    hivemind_enterprise_platform: str = "chatbot"
    hivemind_enterprise_project: str = "enterprise/chat"
    hivemind_enterprise_agent_name: str = "blaiq-agent"
    hivemind_timeout_seconds: int = 45
    hivemind_web_poll_interval_seconds: float = 1.0
    hivemind_web_poll_attempts: int = 10
    hivemind_oauth_url: str = "https://core.hivemind.davinciai.eu:8050"
    hivemind_oauth_authorize_url: str = "https://core.hivemind.davinciai.eu:8050/oauth/authorize"
    hivemind_oauth_token_url: str = "https://core.hivemind.davinciai.eu:8050/oauth/token"
    hivemind_oauth_revoke_url: str = "https://core.hivemind.davinciai.eu:8050/oauth/revoke"
    hivemind_oauth_client_id: str | None = None  # Must be set via env
    hivemind_oauth_redirect_uri: str = "http://localhost:3003/api/hivemind/callback"  # Must match registered URI
    hivemind_oauth_token: str | None = None  # Encrypted server-side in production
    tavily_api_key: str | None = None
    research_max_depth: int = 3
    research_max_iters: int = 15


settings = Settings()
