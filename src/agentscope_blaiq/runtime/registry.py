from __future__ import annotations

from datetime import datetime, timezone

from agentscope_blaiq.contracts.agent_catalog import AgentCapability, AgentSkill, AgentStatus, LiveAgentProfile
from agentscope_blaiq.runtime.model_resolver import LiteLLMModelResolver
from agentscope_blaiq.agents.clarification import ClarificationAgent
from agentscope_blaiq.agents.graph_stub import GraphKnowledgeAgent
from agentscope_blaiq.agents.content_director import ContentDirectorAgent
from agentscope_blaiq.agents.governance import GovernanceAgent
from agentscope_blaiq.agents.deep_research import BlaiqDeepResearchAgent, FinanceDeepResearchAgent
from agentscope_blaiq.agents.data_science import DataScienceAgent
from agentscope_blaiq.agents.research import ResearchAgent
from agentscope_blaiq.agents.strategic import StrategicAgent
from agentscope_blaiq.agents.text_buddy import TextBuddyAgent
from agentscope_blaiq.agents.vangogh import VangoghAgent
from agentscope_blaiq.runtime.config import settings
from agentscope_blaiq.runtime.hivemind_mcp import HivemindMCPClient


class AgentRegistry:
    def __init__(self) -> None:
        self.resolver = LiteLLMModelResolver.from_settings(settings)
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
        self.strategist = StrategicAgent(resolver=self.resolver, catalog_provider=self.list_live_profiles)
        self.hitl = ClarificationAgent(resolver=self.resolver)
        self.research = ResearchAgent(resolver=self.resolver, hivemind=self.hivemind)
        self.deep_research = BlaiqDeepResearchAgent(
            hivemind=self.hivemind,
            resolver=self.resolver,
        )
        self.finance_research = FinanceDeepResearchAgent(
            hivemind=self.hivemind,
            resolver=self.resolver,
        )
        self.data_science = DataScienceAgent(
            hivemind=self.hivemind,
            resolver=self.resolver,
        )
        self.content_director = ContentDirectorAgent(resolver=self.resolver)
        self.vangogh = VangoghAgent(resolver=self.resolver)
        self.text_buddy = TextBuddyAgent(resolver=self.resolver)
        self.governance = GovernanceAgent(resolver=self.resolver)
        self.graph_knowledge = GraphKnowledgeAgent() if settings.enable_graph_agent else None
        self._runtime_state: dict[str, dict[str, object]] = {}

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

    def list_live_profiles(self) -> list[LiveAgentProfile]:
        agents = [
            LiveAgentProfile(
                name="strategist",
                role="workflow topology",
                status=AgentStatus.ready,
                model=self.resolver.resolve("strategic").model_name,
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
                status=AgentStatus.ready,
                model=self.resolver.resolve("hitl").model_name,
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
                status=AgentStatus.ready,
                model=self.resolver.resolve("research").model_name,
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
                status=AgentStatus.ready,
                model=self.resolver.resolve("research").model_name,
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
                status=AgentStatus.ready,
                model=self.resolver.resolve("research").model_name,
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
                status=AgentStatus.ready,
                model=self.resolver.resolve("data_scientist").model_name,
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
                status=AgentStatus.ready,
                model=self.resolver.resolve("content_director").model_name,
                capabilities=[
                    AgentCapability(name="content_distribution", description="Map requirements into a section-by-section content plan.", supported_task_types=["planning", "content"], supported_task_roles=["content_director"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                    AgentCapability(name="section_planning", description="Plan content sections and their ordering.", supported_task_types=["planning", "content"], supported_task_roles=["content_director"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                ],
                skills=[
                    AgentSkill(name="template_selection", level="core"),
                    AgentSkill(name="render_brief_generation", level="core"),
                ],
                tools=["content_distribution", "section_planning", "template_selection", "render_brief_generation"],
                planner_roles=["content_director"],
            ),
            LiveAgentProfile(
                name="vangogh",
                role="visual artifact generation",
                status=AgentStatus.ready,
                model=self.resolver.resolve("vangogh").model_name,
                capabilities=[
                    AgentCapability(name="artifact_layout", description="Shape presentation decks and long-form visuals.", supported_task_types=["design", "presentation"], supported_task_roles=["vangogh"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                    AgentCapability(name="html_css_composition", description="Produce HTML/CSS artifact previews.", supported_task_types=["artifact", "preview"], supported_task_roles=["vangogh"], supported_artifact_families=["pitch_deck", "keynote", "poster", "brochure", "one_pager", "landing_page", "report", "finance_analysis"]),
                ],
                skills=[
                    AgentSkill(name="information_hierarchy", level="core"),
                    AgentSkill(name="editorial_layout", level="core"),
                ],
                tools=["artifact_contract"],
            ),
            LiveAgentProfile(
                name="text_buddy",
                role="brand-voice text composition",
                status=AgentStatus.ready,
                model=self.resolver.resolve("text_buddy").model_name,
                capabilities=[
                    AgentCapability(name="text_composition", description="Compose final text outputs (emails, invoices, letters, memos, proposals, social posts, summaries) in brand voice.", supported_task_types=["writing", "composition"], supported_task_roles=["text_buddy"], supported_artifact_families=["email", "invoice", "letter", "memo", "proposal", "social_post", "summary"]),
                    AgentCapability(name="brand_voice_writing", description="Apply enterprise-specific brand voice guidelines to all text output.", supported_task_types=["writing", "brand"], supported_task_roles=["text_buddy"], supported_artifact_families=["email", "invoice", "letter", "memo", "proposal", "social_post", "summary"]),
                    AgentCapability(name="template_formatting", description="Format text according to artifact-specific templates (email structure, invoice layout, etc.).", supported_task_types=["writing", "formatting"], supported_task_roles=["text_buddy"], supported_artifact_families=["email", "invoice", "letter", "memo", "proposal", "social_post", "summary"]),
                ],
                skills=[
                    AgentSkill(name="brand_voice_application", level="core"),
                    AgentSkill(name="text_template_adherence", level="core"),
                    AgentSkill(name="evidence_citation", level="core"),
                ],
                tools=["apply_brand_voice", "select_template", "format_output"],
                planner_roles=["text_buddy"],
                notes=["Text counterpart to VanGogh — handles all non-visual artifact output in brand voice."],
            ),
            LiveAgentProfile(
                name="governance",
                role="validation",
                status=AgentStatus.ready,
                model=self.resolver.resolve("governance").model_name,
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
                    status=AgentStatus.disabled,
                    model=self.resolver.resolve("graph_knowledge").model_name,
                    capabilities=[
                        AgentCapability(name="graph_retrieval", description="Traverse knowledge graphs for private corpus retrieval.", supported_task_types=["knowledge", "graph"]),
                    ],
                    skills=[AgentSkill(name="graph_reasoning", level="future")],
                    tools=["gather"],
                    notes=["Reserved future agent"],
                )
            )
        return [self._overlay_runtime_state(agent) for agent in agents]

    def list_live(self) -> list[dict[str, object]]:
        return [agent.model_dump() for agent in self.list_live_profiles()]
