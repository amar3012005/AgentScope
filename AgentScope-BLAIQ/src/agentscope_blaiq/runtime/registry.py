from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agentscope_blaiq.contracts.agent_catalog import (
    AgentCapability,
    AgentKind,
    AgentRuntimeFeatures,
    AgentSourceMetadata,
    AgentSkill,
    AgentStatus,
    AgentTransport,
    LiveAgentProfile,
    RuntimeKind,
)
from agentscope_blaiq.contracts.custom_agents import CustomAgentSpec
from agentscope_blaiq.contracts.registry import get_registry, HarnessRegistry
from agentscope_blaiq.contracts.user_agent_registry import UserAgentRegistry
from agentscope_blaiq.runtime.agent_profile_store import AgentProfileDocumentStore
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.agents.remote_proxy import RemoteA2AProxy
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient


class AgentRegistry:
    def __init__(self) -> None:
        self.resolver = LiteLLMModelResolver.from_settings(settings)
        self.harness_registry: HarnessRegistry = get_registry()
        self.user_agent_registry = UserAgentRegistry(self.harness_registry)
        self.hivemind = HivemindMCPClient(
            rpc_url=settings.hivemind_mcp_rpc_url,
            api_key=settings.hivemind_api_key,
            enterprise_base_url=settings.hivemind_enterprise_base_url,
            enterprise_api_key=settings.hivemind_enterprise_api_key,
            enterprise_org_id=settings.hivemind_enterprise_org_id,
            enterprise_user_id=settings.hivemind_enterprise_user_id,
            enterprise_platform=settings.hivemind_enterprise_platform,
            enterprise_project=settings.hivemind_enterprise_project,
            enterprise_agent_name=settings.hivemind_enterprise_agent_name,
            timeout_seconds=settings.hivemind_timeout_seconds,
            poll_interval_seconds=settings.hivemind_web_poll_interval_seconds,
            poll_attempts=settings.hivemind_web_poll_attempts,
        )
        self.graph_knowledge = None
        self._runtime_state: dict[str, dict[str, object]] = {}
        self.profile_store = AgentProfileDocumentStore(settings.agent_profile_dir)
        self._remote_profiles: dict[str, LiveAgentProfile] = {}
        self._load_persisted_profiles()
        self._builtin_agent_factories: dict[str, Any] = {}
        self._builtin_agents: dict[str, Any] = {
            key: factory()
            for key, factory in self._builtin_agent_factories.items()
        }
        if self.graph_knowledge is not None:
            self._builtin_agents["graph_knowledge"] = self.graph_knowledge

    def _load_persisted_profiles(self) -> None:
        for profile in self.profile_store.load_remote_profiles():
            self._remote_profiles[profile.profile_id] = self._overlay_runtime_state(profile)

    def _default_runtime_state(self, name: str) -> dict[str, object]:
        return {
            "status": AgentStatus.ready,
            "current_stage": None,
            "current_load": 0.0,
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "notes": [],
            "planner_roles": [],
        }

    def set_agent_state(
        self,
        name: str,
        *,
        status: AgentStatus | str | None = None,
        current_stage: str | None = None,
        current_load: float | None = None,
        notes: list[str] | None = None,
    ) -> None:
        state = self._runtime_state.setdefault(name, self._default_runtime_state(name))
        if status is not None:
            state["status"] = status if isinstance(status, AgentStatus) else AgentStatus(status)
        if current_stage is not None:
            state["current_stage"] = current_stage
        if current_load is not None:
            state["current_load"] = current_load
        if notes is not None:
            state["notes"] = notes
        state["last_seen"] = datetime.now(timezone.utc).isoformat()

    def mark_agent_busy(self, name: str, stage: str | None = None) -> None:
        self.set_agent_state(name, status=AgentStatus.busy, current_stage=stage)

    def mark_agent_ready(self, name: str, stage: str | None = None) -> None:
        self.set_agent_state(name, status=AgentStatus.ready, current_stage=stage)

    def _overlay_runtime_state(self, profile: LiveAgentProfile) -> LiveAgentProfile:
        state = self._runtime_state.get(profile.name)
        if not state:
            return profile
        return profile.model_copy(
            update={
                "status": state.get("status", profile.status),
                "current_stage": state.get("current_stage", profile.current_stage),
                "current_load": float(state.get("current_load", profile.current_load)),
                "last_seen": state.get("last_seen", profile.last_seen),
                "notes": list(state.get("notes", profile.notes)),
                "planner_roles": list(state.get("planner_roles", profile.planner_roles)),
            }
        )

    def _builtin_live_profiles(self) -> list[LiveAgentProfile]:
        agents = [
            LiveAgentProfile(
                name="strategist",
                role="workflow topology",
                description="Plans workflow topology, artifact routing, and agent assignments.",
                status=AgentStatus.ready,
                model=self.resolver.resolve("strategic").model_name,
                runtime_kind=RuntimeKind.custom_base,
                capabilities=[
                    AgentCapability(name="route_planning", description="Select sequential, parallel, or hybrid workflow topology.", supported_task_types=["routing", "planning"], supported_task_roles=["strategist"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                    AgentCapability(name="task_graph_authoring", description="Build ordered task graphs from live agent inventory.", supported_task_types=["planning", "orchestration"], supported_task_roles=["strategist"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                ],
                skills=[
                    AgentSkill(name="workflow_decomposition", level="core"),
                    AgentSkill(name="topology_selection", level="core"),
                ],
                tools=["list_live_agents", "match_agent_capabilities", "compose_execution_strategy", "classify_artifact_family", "derive_artifact_requirements", "compute_missing_requirements", "compose_task_graph"],
                planner_roles=["strategist", "requirements_planner"],
            ),
            LiveAgentProfile(
                name="hitl",
                role="human clarification",
                description="Asks evidence-aware clarification questions and blocks/resumes workflows.",
                status=AgentStatus.ready,
                model=self.resolver.resolve("hitl").model_name,
                runtime_kind=RuntimeKind.custom_base,
                capabilities=[
                    AgentCapability(name="clarification_dialogue", description="Frame missing requirements as natural language questions.", supported_task_types=["clarification", "interview"], supported_task_roles=["hitl"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                ],
                skills=[
                    AgentSkill(name="question_framing", level="core"),
                    AgentSkill(name="requirement_refinement", level="core"),
                ],
                tools=["clarify_requirements"],
                planner_roles=["hitl"],
                notes=["Uses Sonnet-class model for user-friendly clarification prompts."],
            ),
            LiveAgentProfile(
                name="research",
                role="retrieval and synthesis",
                description="Gathers memory, graph, document, and freshness evidence.",
                status=AgentStatus.ready,
                model=self.resolver.resolve("research").model_name,
                runtime_kind=RuntimeKind.custom_base,
                capabilities=[
                    AgentCapability(name="memory_retrieval", description="Recall internal enterprise memory before using external sources.", supported_task_types=["research", "memory"], supported_task_roles=["research"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                    AgentCapability(name="memory_synthesis", description="Synthesize answers and briefs over HIVE-MIND memory.", supported_task_types=["research", "memory"], supported_task_roles=["research"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                    AgentCapability(name="graph_context_retrieval", description="Traverse linked memories and historical decisions when the query depends on related context.", supported_task_types=["research", "graph"], supported_task_roles=["research"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                    AgentCapability(name="web_freshness_verification", description="Use live web intelligence only when freshness or external verification is required.", supported_task_types=["research", "web"], supported_task_roles=["research"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                    AgentCapability(name="web_research", description="Backward-compatible alias for live web freshness verification.", supported_task_types=["research", "web"], supported_task_roles=["research"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                    AgentCapability(name="document_research", description="Scan uploaded tenant documents as an additional source of evidence.", supported_task_types=["research", "docs"], supported_task_roles=["research"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                ],
                skills=[
                    AgentSkill(name="memory_first_retrieval", level="core"),
                    AgentSkill(name="evidence_synthesis", level="core"),
                    AgentSkill(name="source_citation", level="core"),
                ],
                tools=[
                    "hivemind_recall",
                    "hivemind_query_with_ai",
                    "hivemind_get_memory",
                    "hivemind_traverse_graph",
                    "hivemind_web_search",
                    "hivemind_web_crawl",
                    "hivemind_web_job_status",
                    "hivemind_web_usage",
                    "validate_document_path",
                ],
                planner_roles=["research"],
                notes=[
                    "Uses HIVE-MIND as the primary ground truth and live web only as a freshness layer.",
                    "Memory write-back is explicit and policy-gated; it is not automatic in the default run path.",
                ],
            ),
            LiveAgentProfile(
                name="deep_research",
                role="deep tree-search research",
                description="Performs decomposed research across HIVE-MIND and web tools.",
                status=AgentStatus.ready,
                model=self.resolver.resolve("research").model_name,
                runtime_kind=RuntimeKind.custom_base,
                capabilities=[
                    AgentCapability(name="deep_research", description="Decompose queries into sub-questions and research each via HIVE-MIND and web.", supported_task_types=["research", "deep_research"], supported_task_roles=["research"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                ],
                skills=[
                    AgentSkill(name="tree_search_research", level="core"),
                    AgentSkill(name="evidence_synthesis", level="core"),
                ],
                tools=["hivemind_recall", "hivemind_query_with_ai", "hivemind_web_search"],
                planner_roles=["research"],
                notes=["Deep research agent with query decomposition; replaces flat ResearchAgent for non-finance modes."],
            ),
            LiveAgentProfile(
                name="finance_research",
                role="hypothesis-driven finance research",
                description="Runs finance-specific hypothesis research and verification.",
                status=AgentStatus.ready,
                model=self.resolver.resolve("research").model_name,
                runtime_kind=RuntimeKind.custom_base,
                capabilities=[
                    AgentCapability(name="finance_research", description="Hypothesis-driven finance research with verification workflow.", supported_task_types=["research", "finance"], supported_task_roles=["research"], supported_artifact_families=["finance_analysis", "report"]),
                ],
                skills=[
                    AgentSkill(name="hypothesis_testing", level="core"),
                    AgentSkill(name="finance_synthesis", level="core"),
                ],
                tools=["hivemind_recall", "hivemind_query_with_ai", "hivemind_web_search"],
                planner_roles=["research"],
                notes=["Finance-specific deep research with hypothesis verification; used when analysis_mode is finance."],
            ),
            LiveAgentProfile(
                name="data_science",
                role="autonomous data analysis",
                description="Processes uploaded data, runs analysis code, and generates data reports.",
                status=AgentStatus.ready,
                model=self.resolver.resolve("data_scientist").model_name,
                runtime_kind=RuntimeKind.custom_base,
                capabilities=[
                    AgentCapability(name="data_upload_processing", description="Process uploaded CSV, Excel, and JSON files with schema inference.", supported_task_types=["data_analysis", "upload_processing"], supported_task_roles=["data_science"], supported_artifact_families=["report", "finance_analysis", "dashboard"]),
                    AgentCapability(name="sandboxed_code_execution", description="Execute Python data analysis code in secure Docker sandbox.", supported_task_types=["data_analysis", "code_execution"], supported_task_roles=["data_science"], supported_artifact_families=["report", "finance_analysis", "dashboard"]),
                    AgentCapability(name="statistical_analysis", description="Perform descriptive statistics, correlation analysis, and hypothesis testing.", supported_task_types=["data_analysis", "statistics"], supported_task_roles=["data_science"], supported_artifact_families=["report", "finance_analysis", "dashboard"]),
                    AgentCapability(name="visualization_generation", description="Generate charts and plots using plotly, matplotlib, and seaborn.", supported_task_types=["data_analysis", "visualization"], supported_task_roles=["data_science"], supported_artifact_families=["report", "finance_analysis", "dashboard"]),
                    AgentCapability(name="automated_report_generation", description="Generate HTML reports with insights, visualizations, and executable code.", supported_task_types=["data_analysis", "reporting"], supported_task_roles=["data_science"], supported_artifact_families=["report", "finance_analysis", "dashboard"]),
                ],
                skills=[
                    AgentSkill(name="data_loading", level="core"),
                    AgentSkill(name="statistical_modeling", level="core"),
                    AgentSkill(name="data_visualization", level="core"),
                    AgentSkill(name="insight_generation", level="core"),
                ],
                tools=["data_upload", "sandbox_execute", "statistical_test", "generate_visualization"],
                planner_roles=["data_science"],
                notes=["Autonomous data analysis agent with sandboxed code execution; used when analysis_mode is data_science."],
            ),
            LiveAgentProfile(
                name="content_director",
                role="content planning",
                description="Turns requirements and evidence into artifact briefs and section plans.",
                status=AgentStatus.ready,
                model=self.resolver.resolve("content_director").model_name,
                runtime_kind=RuntimeKind.custom_base,
                capabilities=[
                    AgentCapability(name="artifact_briefing", description="Produce structured artifact briefs with section plans from requirements and evidence.", supported_task_types=["planning", "briefing"], supported_task_roles=["content_director"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                    AgentCapability(name="section_planning", description="Decompose artifacts into ordered sections with intent, evidence, and visual directives.", supported_task_types=["planning"], supported_task_roles=["content_director"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report"]),
                ],
                skills=[
                    AgentSkill(name="brief_authoring", level="core"),
                    AgentSkill(name="narrative_structuring", level="core"),
                ],
                tools=["generate_brief", "plan_sections"],
                planner_roles=["content_director"],
            ),
            LiveAgentProfile(
                name="vangogh",
                role="visual artifact generation",
                description="Renders visual artifact structures and HTML previews.",
                status=AgentStatus.ready,
                model=self.resolver.resolve("vangogh").model_name,
                runtime_kind=RuntimeKind.custom_base,
                capabilities=[
                    AgentCapability(name="visual_rendering", description="Render pitch decks, posters, and visual HTML artifacts from briefs.", supported_task_types=["rendering", "visual"], supported_task_roles=["vangogh"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page"]),
                ],
                skills=[
                    AgentSkill(name="html_rendering", level="core"),
                    AgentSkill(name="brand_application", level="core"),
                ],
                tools=["render_visual_artifact"],
                planner_roles=["vangogh"],
            ),
            LiveAgentProfile(
                name="text_buddy",
                role="brand-voice text composition",
                description="Writes text artifacts using AgentScope skills and brand voice.",
                status=AgentStatus.ready,
                model=self.resolver.resolve("text_buddy").model_name,
                runtime_kind=RuntimeKind.custom_base,
                capabilities=[
                    AgentCapability(name="text_artifact_generation", description="Write professional text artifacts (emails, posts, memos, proposals) in brand voice.", supported_task_types=["writing", "composition"], supported_task_roles=["text_buddy"], supported_artifact_families=["email", "summary", "social_post", "memo", "proposal", "letter", "invoice", "report"]),
                ],
                skills=[
                    AgentSkill(name="brand_voice_writing", level="core"),
                    AgentSkill(name="template_synthesis", level="core"),
                ],
                tools=["write_text_artifact"],
                planner_roles=["text_buddy"],
                notes=["Text counterpart to VanGogh — handles all non-visual artifact output in brand voice."],
            ),
            LiveAgentProfile(
                name="governance",
                role="validation",
                description="Validates artifact quality, completeness, policy, and readiness.",
                status=AgentStatus.ready,
                model=self.resolver.resolve("governance").model_name,
                runtime_kind=RuntimeKind.custom_base,
                capabilities=[
                    AgentCapability(name="artifact_validation", description="Check completeness, citations, and readiness.", supported_task_types=["review", "validation"], supported_task_roles=["governance"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                ],
                skills=[
                    AgentSkill(name="quality_gate", level="core"),
                    AgentSkill(name="policy_review", level="core"),
                ],
                tools=["validate_visual_artifact"],
                planner_roles=["governance"],
            ),
        ]
        if self.graph_knowledge is not None:
            agents.append(
                LiveAgentProfile(
                    name="graph_knowledge",
                    role="future graph knowledge agent",
                    description="Reserved graph retrieval agent.",
                    status=AgentStatus.disabled,
                    model=self.resolver.resolve("graph_knowledge").model_name,
                    runtime_kind=RuntimeKind.custom_base,
                    capabilities=[
                        AgentCapability(name="graph_retrieval", description="Traverse knowledge graphs for private corpus retrieval.", supported_task_types=["knowledge", "graph"]),
                    ],
                    skills=[AgentSkill(name="graph_reasoning", level="future")],
                    tools=["gather"],
                    notes=["Reserved future agent"],
                )
            )
        return [self._overlay_runtime_state(agent) for agent in agents]

    def _custom_live_profile(self, spec: CustomAgentSpec, base_profiles: dict[str, LiveAgentProfile]) -> LiveAgentProfile:
        role_key = str(spec.role or "").strip().lower()
        base_profile = base_profiles.get(role_key)

        if base_profile is not None:
            capabilities = [cap.model_copy(deep=True) for cap in base_profile.capabilities]
            skills = [skill.model_copy(deep=True) for skill in base_profile.skills]
            tools = list(spec.allowed_tools or base_profile.tools)
            planner_roles = list(base_profile.planner_roles)
            model_name = base_profile.model
            notes = list(base_profile.notes)
        else:
            capabilities = [
                AgentCapability(
                    name=role_key or "custom_execution",
                    description=f"Custom agent capability for role '{spec.role}'.",
                    supported_task_types=["custom"],
                    supported_task_roles=[role_key] if role_key else ["custom"],
                    supported_artifact_families=[spec.artifact_family] if spec.artifact_family else [],
                )
            ]
            skills = [AgentSkill(name="custom_prompt_execution", level="custom")]
            tools = list(spec.allowed_tools)
            planner_roles = [role_key] if role_key else ["custom"]
            model_name = spec.model_hint
            notes = []

        notes.append("Custom user-defined agent registered through harness contracts.")
        notes.append(f"Display name: {spec.display_name}")

        profile = LiveAgentProfile(
            name=spec.agent_id,
            role=spec.role,
            description=spec.display_name,
            status=AgentStatus.ready,
            model=model_name,
            agent_kind=AgentKind.custom,
            transport=AgentTransport.local,
            runtime_kind=RuntimeKind.custom_base,
            capabilities=capabilities,
            skills=skills,
            tools=tools,
            planner_roles=planner_roles,
            notes=notes,
            tags=list(spec.tags) if spec.tags else [],
            artifact_affinities=[spec.artifact_family] if spec.artifact_family else [],
            is_custom=True,
        )
        return self._overlay_runtime_state(profile)

    def list_live_profiles(self) -> list[LiveAgentProfile]:
        agents = self._builtin_live_profiles()
        base_profiles = {agent.name: agent for agent in agents}
        custom_profiles = [
            self._custom_live_profile(spec, base_profiles)
            for spec in self.user_agent_registry.list_all()
        ]
        return [*agents, *custom_profiles, *self._remote_profiles.values()]

    def list_live(self) -> list[dict[str, object]]:
        return [agent.model_dump(mode="json") for agent in self.list_live_profiles()]

    def list_profiles(
        self,
        *,
        role: str | None = None,
        capability: str | None = None,
        skill: str | None = None,
        tool: str | None = None,
        transport: str | AgentTransport | None = None,
        status: str | AgentStatus | None = None,
        artifact_family: str | None = None,
    ) -> list[LiveAgentProfile]:
        profiles = self.list_live_profiles()
        if role:
            profiles = [
                p for p in profiles
                if p.role == role or role in p.planner_roles or any(role in cap.supported_task_roles for cap in p.capabilities)
            ]
        if capability:
            profiles = [p for p in profiles if capability in p.capability_names]
        if skill:
            profiles = [p for p in profiles if skill in p.skill_names]
        if tool:
            profiles = [p for p in profiles if tool in p.tools]
        if transport:
            transport_value = transport.value if isinstance(transport, AgentTransport) else str(transport)
            profiles = [p for p in profiles if p.transport.value == transport_value]
        if status:
            status_value = status.value if isinstance(status, AgentStatus) else str(status)
            profiles = [p for p in profiles if p.status.value == status_value]
        if artifact_family:
            profiles = [
                p for p in profiles
                if artifact_family in p.artifact_affinities
                or any(artifact_family in cap.supported_artifact_families for cap in p.capabilities)
            ]
        return profiles

    def get_profile(self, profile_id: str) -> LiveAgentProfile | None:
        for profile in self.list_live_profiles():
            if profile.profile_id == profile_id or profile.name == profile_id:
                return profile
        return None

    def profile_catalog_response(self, **filters: Any) -> dict[str, object]:
        profiles = self.list_profiles(**filters)
        return {
            "count": len(profiles),
            "profiles": [profile.model_dump(mode="json") for profile in profiles],
            "routing_index": [profile.routing_index() for profile in profiles],
            "filters": {key: value for key, value in filters.items() if value not in (None, "")},
        }

    def register_remote_agent_card(self, card: dict[str, Any], *, source_ref: str | None = None) -> LiveAgentProfile:
        name = str(card.get("name") or card.get("id") or card.get("agent_id") or "").strip()
        if not name:
            raise ValueError("Remote Agent Card must include a name, id, or agent_id")

        profile_id = str(card.get("profile_id") or name).strip()
        description = str(card.get("description") or card.get("summary") or "").strip()
        endpoint_ref = str(card.get("url") or card.get("endpoint") or source_ref or "").strip() or None
        raw_skills = card.get("skills") or []
        raw_capabilities = card.get("capabilities") or []

        skills: list[AgentSkill] = []
        for skill in raw_skills if isinstance(raw_skills, list) else []:
            if isinstance(skill, dict):
                skill_name = str(skill.get("name") or skill.get("id") or "").strip()
                skill_level = str(skill.get("level") or "remote").strip() or "remote"
            else:
                skill_name = str(skill).strip()
                skill_level = "remote"
            if skill_name:
                skills.append(AgentSkill(name=skill_name, level=skill_level))

        capabilities: list[AgentCapability] = []
        if isinstance(raw_capabilities, dict):
            raw_capabilities = [
                {"name": key, "description": str(value)}
                for key, value in raw_capabilities.items()
            ]
        for capability in raw_capabilities if isinstance(raw_capabilities, list) else []:
            if isinstance(capability, dict):
                cap_name = str(capability.get("name") or capability.get("id") or "").strip()
                cap_description = str(capability.get("description") or cap_name).strip()
                task_roles = list(capability.get("supported_task_roles") or capability.get("roles") or [])
                families = list(capability.get("supported_artifact_families") or capability.get("artifact_families") or [])
            else:
                cap_name = str(capability).strip()
                cap_description = cap_name
                task_roles = []
                families = []
            if cap_name:
                capabilities.append(
                    AgentCapability(
                        name=cap_name,
                        description=cap_description,
                        supported_task_roles=task_roles,
                        supported_artifact_families=families,
                    )
                )

        if not capabilities and skills:
            capabilities = [
                AgentCapability(
                    name=skill.name,
                    description=f"Remote skill from Agent Card: {skill.name}",
                    supported_task_roles=[skill.name],
                )
                for skill in skills
            ]

        tools = [
            str(tool.get("id") or tool.get("name") if isinstance(tool, dict) else tool).strip()
            for tool in (card.get("tools") or [])
        ]
        tools = [tool for tool in tools if tool]

        profile = LiveAgentProfile(
            profile_id=profile_id,
            name=name,
            role=str(card.get("role") or "remote agent").strip() or "remote agent",
            description=description,
            agent_kind=AgentKind.remote,
            transport=AgentTransport.remote_a2a,
            runtime_kind=RuntimeKind.a2a,
            status=AgentStatus.ready,
            model=card.get("model"),
            capabilities=capabilities,
            skills=skills,
            tools=tools,
            tags=list(card.get("tags") or ["remote-a2a"]),
            artifact_affinities=list(card.get("artifact_affinities") or []),
            planner_roles=list(card.get("planner_roles") or []),
            runtime_features=AgentRuntimeFeatures(
                session_capable=True,
                planning_capable=False,
                structured_output_capable=False,
                interrupt_capable=False,
                tool_calling_capable=bool(tools),
            ),
            source_metadata=AgentSourceMetadata(
                source="remote-a2a",
                raw={"agent_card": card, "source_ref": source_ref},
            ),
            profile_document=card,
        )
        profile.execution.endpoint_ref = endpoint_ref
        profile.execution.agent_card_ref = source_ref
        self._remote_profiles[profile.profile_id] = self._overlay_runtime_state(profile)
        self.profile_store.save_profile(self._remote_profiles[profile.profile_id])
        return self._remote_profiles[profile.profile_id]

    def get_agent(self, agent_name: str) -> Any | None:
        if agent_name in self._builtin_agents:
            return self._builtin_agents[agent_name]

        # Check for remote profiles
        if agent_name in self._remote_profiles:
            profile = self._remote_profiles[agent_name]
            if profile.transport == AgentTransport.remote_a2a:
                endpoint = profile.execution.endpoint_ref
                if endpoint:
                    return RemoteA2AProxy(
                        endpoint_url=endpoint,
                        name=profile.name,
                        role=profile.role,
                        resolver=self.resolver,
                    )

        spec = self.user_agent_registry.get(agent_name)
        if spec is None:
            return None

        role_key = str(spec.role or "").strip().lower()
        agent = self._builtin_agent_for_role(role_key)
        if agent is None:
            return None

        agent.name = spec.display_name or spec.agent_id
        agent.role = role_key or agent.role
        agent.sys_prompt = spec.prompt
        agent.status_messages = spec.status_messages or []
        return agent


    def _builtin_agent_for_role(self, role_key: str) -> Any | None:
        factory = self._builtin_agent_factories.get(role_key)
        if factory is None:
            return None
        return factory()
