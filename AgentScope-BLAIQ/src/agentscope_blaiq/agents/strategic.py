from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agentscope.tool import Toolkit
from pydantic import BaseModel, Field

from agentscope_blaiq.contracts.agent_catalog import AgentTaskAssignment, AgentStatus, LiveAgentProfile
from agentscope_blaiq.contracts.workflow import (
    AgentRunPayload,
    AgentType,
    AnalysisMode,
    ArtifactFamily,
    ArtifactSpec,
    ExecutorKind,
    RequirementItem,
    RequirementStage,
    RequirementsChecklist,
    SubmitWorkflowRequest,
    WorkflowEdge,
    TaskGraph,
    TaskRole,
    WorkflowMode,
    WorkflowNode,
    WorkflowPlan,
)
from agentscope_blaiq.runtime.agent_base import BaseAgent


class StrategicDraft(BaseModel):
    workflow_mode: WorkflowMode
    analysis_mode: AnalysisMode = AnalysisMode.standard
    summary: str
    task_count: int = Field(ge=0)
    notes: list[str] = Field(default_factory=list)
    topology_reason: str = ""
    artifact_family: ArtifactFamily = ArtifactFamily.custom
    artifact_spec: ArtifactSpec | None = None
    requirements_checklist: RequirementsChecklist = Field(default_factory=RequirementsChecklist)
    task_graph: TaskGraph = Field(default_factory=TaskGraph)
    hitl_nodes: list[WorkflowNode] = Field(default_factory=list)
    content_director_nodes: list[WorkflowNode] = Field(default_factory=list)
    # Phase 3: Strict route metadata for dispatch enforcement
    workflow_template_id: str | None = None
    node_assignments: dict[str, str] = Field(default_factory=dict)  # node_id -> agent_id
    required_tools_per_node: dict[str, list[str]] = Field(default_factory=dict)  # node_id -> [tool_id]
    fallback_path: str | None = None
    missing_requirements: list[str] = Field(default_factory=list)

    @classmethod
    def validate_routing(
        cls,
        draft: StrategicDraft,
        user_registry: Any,
    ) -> tuple[bool, list[str]]:
        """
        Validate that all ``node_assignments`` in *draft* are routable.

        Checks both built-in and custom agents:

        * **Custom agents** (those present in *user_registry*) are validated
          via :meth:`~agentscope_blaiq.contracts.user_agent_registry.UserAgentRegistry.validate_draft_routing`.
        * **Built-in agents** are checked for existence in the harness
          registry exposed by ``user_registry._harness_registry``.

        This is a lightweight static-style method that other code can call to
        validate a draft before execution begins.

        Args:
            draft:         The :class:`StrategicDraft` whose assignments
                           should be validated.
            user_registry: A
                :class:`~agentscope_blaiq.contracts.user_agent_registry.UserAgentRegistry`
                instance (typed as ``Any`` to avoid circular imports).

        Returns:
            A ``(ok, errors)`` tuple.  ``ok`` is ``True`` only when every
            assigned agent passes validation.
        """
        errors: list[str] = []

        if not draft.node_assignments:
            return True, []

        workflow_id = draft.workflow_template_id or ""

        # Separate custom vs built-in agent assignments.
        custom_assignments: dict[str, str] = {}
        builtin_assignments: dict[str, str] = {}

        custom_ids: set[str] = set(user_registry.list_ids())
        for node_id, agent_id in draft.node_assignments.items():
            if agent_id in custom_ids:
                custom_assignments[node_id] = agent_id
            else:
                builtin_assignments[node_id] = agent_id

        # Validate custom agents via the user registry.
        if custom_assignments:
            custom_ok, custom_errors = user_registry.validate_draft_routing(
                custom_assignments, workflow_id
            )
            if not custom_ok:
                errors.extend(custom_errors)

        # Validate built-in agents exist in the harness registry.
        harness_registry = user_registry._harness_registry  # noqa: SLF001
        for node_id, agent_id in builtin_assignments.items():
            if harness_registry.get_agent(agent_id) is None:
                errors.append(
                    f"[node={node_id}] Built-in agent '{agent_id}' not found "
                    "in the harness registry."
                )

        return len(errors) == 0, errors


class DirectQueryIntent(BaseModel):
    route: str = Field(description="Either 'direct_answer' or 'artifact'")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""


ARTIFACT_BLUEPRINTS: dict[ArtifactFamily, dict[str, object]] = {
    ArtifactFamily.pitch_deck: {
        "required_sections": ["Hero", "Problem", "Solution", "Proof", "Differentiation", "CTA"],
        "blocking_fields": ["target_audience"],
        "evidence_informed_fields": ["must_have_sections"],
        "template": "pitch-deck-executive",
        "tone": "executive",
        "content_distribution": ["hero", "problem", "solution", "proof", "differentiation", "cta"],
    },
    ArtifactFamily.keynote: {
        "required_sections": ["Opening", "Narrative", "Proof", "Closing"],
        "blocking_fields": ["target_audience"],
        "evidence_informed_fields": ["must_have_sections"],
        "template": "keynote-stage",
        "tone": "presentational",
        "content_distribution": ["opening", "narrative", "proof", "closing"],
    },
    ArtifactFamily.poster: {
        "required_sections": ["Headline", "Visual Hook", "Supporting Proof"],
        "blocking_fields": ["delivery_channel"],
        "evidence_informed_fields": ["must_have_sections"],
        "template": "poster-vertical",
        "tone": "bold",
        "content_distribution": ["headline", "visual", "proof"],
    },
    ArtifactFamily.brochure: {
        "required_sections": ["Cover", "Offer", "Details", "CTA"],
        "blocking_fields": ["target_audience"],
        "evidence_informed_fields": ["must_have_sections"],
        "template": "brochure-fold",
        "tone": "informative",
        "content_distribution": ["cover", "offer", "details", "cta"],
    },
    ArtifactFamily.one_pager: {
        "required_sections": ["Headline", "Value", "Evidence", "CTA"],
        "blocking_fields": ["target_audience"],
        "evidence_informed_fields": ["must_have_sections"],
        "template": "one-pager-executive",
        "tone": "concise",
        "content_distribution": ["headline", "value", "evidence", "cta"],
    },
    ArtifactFamily.landing_page: {
        "required_sections": ["Hero", "Benefits", "Proof", "CTA"],
        "blocking_fields": ["delivery_channel", "target_audience"],
        "evidence_informed_fields": ["must_have_sections"],
        "template": "landing-page-conversion",
        "tone": "conversion",
        "content_distribution": ["hero", "benefits", "proof", "cta"],
    },
    ArtifactFamily.report: {
        "required_sections": ["Executive Summary", "Findings", "Recommendations"],
        "blocking_fields": ["target_audience"],
        "evidence_informed_fields": ["must_have_sections"],
        "template": "report-executive",
        "tone": "analytical",
        "content_distribution": ["summary", "findings", "recommendations"],
    },
    ArtifactFamily.finance_analysis: {
        "required_sections": ["Thesis", "Hypotheses", "Evidence", "Risks", "Recommendation"],
        "blocking_fields": ["analysis_subject", "analysis_objective"],
        "evidence_informed_fields": ["analysis_horizon", "analysis_benchmark"],
        "template": "finance-analysis-executive",
        "tone": "analytical",
        "content_distribution": ["thesis", "hypotheses", "evidence", "risks", "recommendation"],
    },
    ArtifactFamily.custom: {
        "required_sections": ["Hero", "Evidence"],
        "blocking_fields": [],
        "evidence_informed_fields": ["must_have_sections"],
        "template": "default",
        "tone": "executive",
        "content_distribution": ["hero", "evidence"],
    },
    ArtifactFamily.email: {
        "required_sections": ["Subject", "Greeting", "Body", "CTA", "Sign-off"],
        "blocking_fields": ["target_audience"],
        "evidence_informed_fields": [],
        "template": "email",
        "tone": "professional",
        "content_distribution": ["subject", "greeting", "body", "cta", "sign_off"],
    },
    ArtifactFamily.invoice: {
        "required_sections": ["Header", "Line Items", "Totals", "Payment Terms"],
        "blocking_fields": [],
        "evidence_informed_fields": [],
        "template": "invoice",
        "tone": "formal",
        "content_distribution": ["header", "line_items", "totals", "payment_terms"],
    },
    ArtifactFamily.letter: {
        "required_sections": ["Salutation", "Body", "Closing"],
        "blocking_fields": ["target_audience"],
        "evidence_informed_fields": [],
        "template": "letter",
        "tone": "formal",
        "content_distribution": ["salutation", "body", "closing"],
    },
    ArtifactFamily.memo: {
        "required_sections": ["Header", "Summary", "Body", "Action Items"],
        "blocking_fields": [],
        "evidence_informed_fields": [],
        "template": "memo",
        "tone": "direct",
        "content_distribution": ["header", "summary", "body", "action_items"],
    },
    ArtifactFamily.proposal: {
        "required_sections": ["Executive Summary", "Problem", "Solution", "Scope", "Timeline", "Pricing"],
        "blocking_fields": ["target_audience"],
        "evidence_informed_fields": ["must_have_sections"],
        "template": "proposal",
        "tone": "persuasive",
        "content_distribution": ["executive_summary", "problem", "solution", "scope", "timeline", "pricing"],
    },
    ArtifactFamily.social_post: {
        "required_sections": ["Hook", "Body", "CTA"],
        "blocking_fields": [],
        "evidence_informed_fields": [],
        "template": "social_post",
        "tone": "engaging",
        "content_distribution": ["hook", "body", "cta"],
    },
    ArtifactFamily.summary: {
        "required_sections": ["Key Finding", "Evidence", "Analysis", "Recommendation"],
        "blocking_fields": [],
        "evidence_informed_fields": ["must_have_sections"],
        "template": "summary",
        "tone": "analytical",
        "content_distribution": ["key_finding", "evidence", "analysis", "recommendation"],
    },
}

TASK_ROLE_TO_AGENT_TYPE: dict[TaskRole, AgentType] = {
    TaskRole.strategist: AgentType.strategist,
    TaskRole.research: AgentType.research,
    TaskRole.content_director: AgentType.content_director,
    TaskRole.vangogh: AgentType.vangogh,
    TaskRole.governance: AgentType.governance,
    TaskRole.synthesis: AgentType.strategist,
    TaskRole.render: AgentType.vangogh,
    TaskRole.custom: AgentType.strategist,
    TaskRole.text_buddy: AgentType.text_buddy,
}

# Import canonical text families from contracts
from agentscope_blaiq.contracts.workflow import TEXT_ARTIFACT_FAMILIES as TEXT_FAMILIES


class StrategyInspection(BaseModel):
    requested_mode: WorkflowMode
    chosen_mode: WorkflowMode
    topology_reason: str
    ready_agents: list[LiveAgentProfile] = Field(default_factory=list)
    matches: list[AgentTaskAssignment] = Field(default_factory=list)


class StrategicAgent(BaseAgent):
    def __init__(
        self,
        *,
        catalog_provider: Callable[[], list[LiveAgentProfile]] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            name="StrategicAgent",
            role="strategic",
            sys_prompt=(
                "You are the Lead Strategist at BLAIQ. Your core responsibility is to route user requests "
                "to the correct workflow and enforce strict role boundaries.\n\n"
                "ROUTING RULES:\n"
                "1. Choose a workflow template (visual_artifact_v1, text_artifact_v1, research_v1).\n"
                "2. Choose execution_mode: 'staged' (high-quality visual/long-form) or 'single_go' (simple tasks).\n"
                "3. STAGED is mandatory for Pitch Decks, Posters, Landing Pages, and Reports.\n"
                "4. Assign nodes and define tool requirements for each stage.\n\n"
                "Your goal is to build the optimal DAG (Directed Acyclic Graph) for the desired artifact family.\n"
                "Inspect the live agent catalog before choosing a workflow topology and task graph."
            ),
            **kwargs,
        )
        self.catalog_provider = catalog_provider or (lambda: [])

    def build_toolkit(self) -> Toolkit:
        toolkit = Toolkit()
        self.register_tool(toolkit, tool_id="classify_artifact_family", fn=self._tool_classify_artifact_family, description="Classify the request into an artifact family.")
        self.register_tool(toolkit, tool_id="derive_artifact_requirements", fn=self._tool_derive_artifact_requirements, description="Derive the family-specific requirement checklist.")
        self.register_tool(toolkit, tool_id="compute_missing_requirements", fn=self._tool_compute_missing_requirements, description="Compute the missing required items for the current request.")
        self.register_tool(toolkit, tool_id="compose_task_graph", fn=self._tool_compose_task_graph, description="Compose a task graph from the live catalog and requirement checklist.")
        self.register_tool(toolkit, tool_id="match_agents_for_task_role", fn=self._tool_match_agents_for_task_role, description="Match live agents to a planner task role.")
        self.register_tool(toolkit, tool_id="list_live_agents", fn=self._tool_list_live_agents, description="Return the live agent catalog with status, capabilities, skills, tools, and model metadata.")
        self.register_tool(toolkit, tool_id="match_agent_capabilities", fn=self._tool_match_agent_capabilities, description="Match required task capabilities to live agents in the catalog.")
        self.register_tool(toolkit, tool_id="compose_execution_strategy", fn=self._tool_compose_execution_strategy, description="Compose the topology, task assignments, and fan-in strategy from the live catalog.")
        return toolkit

    def _tool_classify_artifact_family(self, request_payload: dict | None = None):
        family = self.classify_artifact_family(request_payload or {})
        return self.tool_response({"artifact_family": family.value})

    def _tool_derive_artifact_requirements(self, request_payload: dict | None = None):
        family = self.classify_artifact_family(request_payload or {})
        checklist = self.derive_artifact_requirements(family, request_payload or {})
        return self.tool_response(checklist.model_dump())

    def _tool_compute_missing_requirements(self, checklist: dict | None = None):
        model = RequirementsChecklist.model_validate(checklist or {})
        return self.tool_response(self.compute_missing_requirements(model).model_dump())

    def _tool_compose_task_graph(self, request_payload: dict | None = None, agent_catalog: list[dict] | None = None):
        family = self.classify_artifact_family(request_payload or {})
        checklist = self.derive_artifact_requirements(family, request_payload or {})
        graph = self.compose_task_graph(family, checklist, [LiveAgentProfile.model_validate(agent) for agent in (agent_catalog or [])])
        return self.tool_response(graph.model_dump())

    def _tool_match_agents_for_task_role(self, task_role: str | None = None, agent_catalog: list[dict] | None = None):
        role = TaskRole(task_role or "custom")
        matches = self.match_agents_for_task_role(role, [LiveAgentProfile.model_validate(agent) for agent in (agent_catalog or [])])
        return self.tool_response(matches)

    def _tool_list_live_agents(self):
        return self.tool_response([agent.model_dump(mode="json") for agent in self.catalog_provider()])

    def _tool_match_agent_capabilities(self, required_capabilities: list[str] | None = None):
        required = {cap.lower() for cap in (required_capabilities or []) if cap}
        matches = []
        for agent in self.catalog_provider():
            capability_names = {cap.name.lower() for cap in agent.capabilities}
            overlap = sorted(required & capability_names)
            if required and not overlap:
                continue
            matches.append(
                {
                    "agent_name": agent.name,
                    "role": agent.role,
                    "status": agent.status.value,
                    "transport": agent.transport.value,
                    "runtime_kind": agent.runtime_kind.value,
                    "matched_capabilities": overlap,
                    "skills": [skill.model_dump(mode="json") for skill in agent.skills],
                    "tools": agent.tools,
                    "model": agent.model,
                    "current_load": agent.current_load,
                }
            )
        return self.tool_response(matches)

    def _tool_compose_execution_strategy(
        self,
        request_payload: dict | None = None,
        agent_catalog: list[dict] | None = None,
    ):
        return self.tool_response(
            {
                "request_payload": request_payload or {},
                "agent_catalog": agent_catalog or [agent.model_dump(mode="json") for agent in self.catalog_provider()],
                "rules": {
                    "sequential": "Use when the workflow is linear or when a required specialist is unavailable.",
                    "parallel": "Use when two or more branches can run independently against distinct live agents.",
                    "hybrid": "Use when research can fan out first, then converge into artifact generation and governance.",
                },
            }
        )

    def _workflow_topology_rules(self):
        return self.tool_response(
            {
                "sequential": "Use when work is linear and later stages depend directly on earlier results.",
                "parallel": "Use when branches can run independently and merge before review.",
                "hybrid": "Use when research should fan out first, then converge into artifact generation.",
            }
        )

    @staticmethod
    def _normalized_query_text(raw_query: str) -> str:
        normalized = "".join(char.lower() if char.isalnum() or char.isspace() else " " for char in raw_query)
        return " ".join(normalized.split())

    @classmethod
    def is_direct_knowledge_query(cls, request_payload: dict[str, object] | SubmitWorkflowRequest) -> bool:
        if isinstance(request_payload, SubmitWorkflowRequest):
            raw_query = request_payload.user_query
        else:
            raw_query = str(request_payload.get("user_query", ""))

        query = cls._normalized_query_text(raw_query)

        if not query:
            return False

        artifact_signals = (
            # Visual artifact verbs
            "create ", "make ", "generate ", "build ", "design ", "render ",
            # Text artifact verbs
            "draft ", "write ", "compose ", "prepare ", "send ", "reply ",
            # Visual artifact families
            "pitch deck", "presentation", "deck", "poster", "brochure", "landing page",
            "one pager", "one-pager", "report", "web page", "webpage",
            # Text artifact families
            "email", "e-mail", "letter", "memo", "memorandum", "invoice", "billing",
            "proposal", "rfp", "social post", "tweet", "linkedin post", "newsletter",
        )
        if any(signal in query for signal in artifact_signals):
            return False

        knowledge_signals = (
            "what do you know", "what do u know", "who am i", "tell me about",
            "what is", "who is", "when is", "where is", "why is", "how does",
            "how do", "do you know", "summarize", "explain", "what can you tell me",
            "give me details", "give me technical", "give me info", "give me the",
            "show me details", "show me technical", "show me info",
            "find me details", "find details", "find info", "find technical",
            "list the", "list all", "describe the", "describe my",
            "what are the", "what are my", "what were the",
        )
        if any(query.startswith(signal) for signal in knowledge_signals):
            return True

        # "give me X about Y" pattern — knowledge request
        if query.startswith("give me") and any(kw in query for kw in ("detail", "info", "spec", "overview", "summary", "standard")):
            return True

        tokens = query.split()
        token_set = set(tokens)
        if {"know", "about", "me"} <= token_set and tokens[:1] and tokens[0] in {"what", "wat", "wht"}:
            return True
        if ("me" in token_set or "my" in token_set or "myself" in token_set) and tokens[:1] and tokens[0] in {
            "what", "wat", "wht", "who", "tell", "summarize", "explain", "give", "show", "find", "list",
        }:
            return True
        # Fuzzy match for "my company/comapny/compny" — common typos
        if any(phrase in query for phrase in (
            "about me", "about myself", "my projects", "my company", "my work",
            "my comapny", "my compny", "my busines", "my team", "my product",
            "my organization", "my org", "my startup", "my brand",
        )):
            return True
        if query.startswith(("how many", "how much", "how long", "how often", "how far")):
            return True
        # Questions ending with ? are knowledge queries
        if raw_query.strip().endswith("?"):
            return True
        # "technical details/specs about X" without create/make/generate
        if any(kw in query for kw in ("technical detail", "revenue standard", "pricing detail", "product spec")):
            return True
        return False

    async def classify_route_llm(self, request: SubmitWorkflowRequest) -> str:
        """Fast LLM three-way route classifier.

        Returns one of: ``"conversational"``, ``"direct_answer"``, ``"artifact"``.
        Falls back to heuristic on LLM failure.
        """
        prompt = (
            f"User request: \"{request.user_query}\"\n\n"
            "Classify this request into ONE of three categories:\n\n"
            "- conversational: greetings, chitchat, thanks, meta-questions about the system, "
            "or anything that does NOT need research or evidence lookup.\n"
            "  Examples: \"hello\", \"thanks\", \"what can you do?\", \"hi there\", \"good morning\", "
            "\"who are you?\", \"how are you?\"\n\n"
            "- direct_answer: asking for facts, details, specs, explanation, summary, what we know. "
            "Requires looking up information from memory or the web.\n"
            "  Examples: \"what is X\", \"tell me about Y\", \"explain Z\", \"give me info on\"\n\n"
            "- artifact: explicitly asks to PRODUCE a deliverable of any kind.\n"
            "  Visual verbs: CREATE/BUILD/GENERATE/RENDER/DESIGN (pitch deck, poster, report)\n"
            "  Text verbs: WRITE/COMPOSE/DRAFT/SEND/PREPARE (email, letter, memo, proposal, social post, invoice)\n"
            "  Examples: \"write an email to...\", \"draft a memo\", \"create a pitch deck\"\n\n"
            "Return ONLY JSON: {\"route\": \"conversational\" or \"direct_answer\" or \"artifact\", \"confidence\": 0.0-1.0}"
        )
        try:
            response = await self.resolver.acompletion(
                "routing",
                [
                    {"role": "system", "content": "You are a fast intent router. Return only JSON. No explanation."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=80,
                temperature=0.0,
            )
            raw = self.resolver.extract_text(response)
            parsed = self.resolver.safe_json_loads(raw)
            route = str(parsed.get("route", "")).strip().lower()
            confidence = float(parsed.get("confidence", 0.5))
            if route in {"conversational", "direct_answer", "artifact"}:
                await self.log(
                    f"LLM routing decision: {route} (confidence {confidence:.2f}).",
                    kind="decision",
                    visibility="debug",
                    detail={"route": route, "confidence": confidence},
                )
                return route
        except Exception as exc:
            await self.log(
                f"LLM route classification failed, falling back to heuristic: {exc}",
                kind="status",
                visibility="debug",
            )
        # Heuristic fallback
        if self._is_conversational_heuristic(request.user_query):
            return "conversational"
        if self.is_direct_knowledge_query(request):
            return "direct_answer"
        return "artifact"

    async def is_direct_knowledge_query_llm(self, request: SubmitWorkflowRequest) -> bool:
        """Backward-compatible wrapper. Returns True for direct_answer route."""
        route = await self.classify_route_llm(request)
        return route == "direct_answer"

    @staticmethod
    def _is_conversational_heuristic(query: str) -> bool:
        """Fast heuristic for greetings/chitchat — no LLM needed."""
        q = query.strip().lower().rstrip("!?.,")
        # Short greetings
        if len(q.split()) <= 3 and any(g in q for g in (
            "hello", "hi", "hey", "hola", "hallo", "good morning", "good evening",
            "good afternoon", "thanks", "thank you", "bye", "goodbye", "cheers",
            "what can you do", "who are you", "how are you", "whats up", "what's up",
            "guten tag", "moin", "servus", "grüß gott",
        )):
            return True
        # Very short messages (1-2 words) that aren't questions about topics
        if len(q.split()) <= 2 and not any(kw in q for kw in (
            "product", "price", "spec", "detail", "info", "data", "report",
            "revenue", "market", "analysis", "create", "make", "write", "draft",
        )):
            return True
        return False

    @staticmethod
    def classify_artifact_family(request_payload: dict[str, object] | SubmitWorkflowRequest) -> ArtifactFamily:
        if isinstance(request_payload, SubmitWorkflowRequest):
            hint = request_payload.artifact_family_hint
            analysis_mode = request_payload.analysis_mode
            query = request_payload.user_query.lower()
            target_audience = (request_payload.target_audience or "").lower()
            delivery_channel = (request_payload.delivery_channel or "").lower()
            sections = [section.lower() for section in request_payload.must_have_sections]
        else:
            hint = request_payload.get("artifact_family_hint")
            analysis_mode = request_payload.get("analysis_mode")
            query = str(request_payload.get("user_query", "")).lower()
            target_audience = str(request_payload.get("target_audience", "")).lower()
            delivery_channel = str(request_payload.get("delivery_channel", "")).lower()
            sections = [str(section).lower() for section in request_payload.get("must_have_sections", [])]

        if hint:
            return hint if isinstance(hint, ArtifactFamily) else ArtifactFamily(str(hint))
        if analysis_mode is not None:
            analysis_mode_value = analysis_mode.value if isinstance(analysis_mode, AnalysisMode) else str(analysis_mode)
            if analysis_mode_value == AnalysisMode.finance.value:
                return ArtifactFamily.finance_analysis

        signal = " ".join([query, target_audience, delivery_channel, " ".join(sections)])
        if any(token in signal for token in ("finance analysis", "financial analysis", "investment analysis", "equity research", "valuation", "earnings", "cash flow", "balance sheet", "income statement")):
            return ArtifactFamily.finance_analysis
        if any(token in signal for token in ("pitch deck", "slide deck", "presentation", "deck")):
            return ArtifactFamily.pitch_deck
        if "keynote" in signal:
            return ArtifactFamily.keynote
        if any(token in signal for token in ("poster", "event poster", "research poster")):
            return ArtifactFamily.poster
        if any(token in signal for token in ("brochure", "booklet", "fold")):
            return ArtifactFamily.brochure
        if any(token in signal for token in ("one pager", "one-pager", "brief", "summary")):
            return ArtifactFamily.one_pager
        if any(token in signal for token in ("landing page", "homepage", "web page", "webpage")):
            return ArtifactFamily.landing_page
        if any(token in signal for token in ("report", "analysis")):
            return ArtifactFamily.report
        # Text-based artifact families
        if any(token in signal for token in ("email", "e-mail", "cold email", "follow up email", "follow-up email", "newsletter")):
            return ArtifactFamily.email
        if any(token in signal for token in ("invoice", "billing", "receipt")):
            return ArtifactFamily.invoice
        if any(token in signal for token in ("letter", "formal letter", "cover letter", "recommendation letter")):
            return ArtifactFamily.letter
        if any(token in signal for token in ("memo", "memorandum", "internal memo")):
            return ArtifactFamily.memo
        if any(token in signal for token in ("proposal", "business proposal", "project proposal", "rfp response")):
            return ArtifactFamily.proposal
        if any(token in signal for token in ("social post", "tweet", "linkedin post", "linked in post", "linked post", "linkedin", "instagram post", "social media")):
            return ArtifactFamily.social_post
        if any(token in signal for token in ("summary", "executive summary", "brief", "executive brief", "recap")):
            return ArtifactFamily.summary
        return ArtifactFamily.custom

    async def _classify_artifact_family_llm(
        self, request: SubmitWorkflowRequest, fallback: ArtifactFamily,
    ) -> ArtifactFamily:
        """LLM-primary artifact family classification.

        Uses a fast LLM call to classify the user's request into an artifact
        family. The heuristic result is passed as ``fallback`` and used only
        when the LLM call fails or returns low confidence.
        """
        # If the request already has an explicit hint, trust it
        if request.artifact_family_hint is not None:
            return (
                request.artifact_family_hint
                if isinstance(request.artifact_family_hint, ArtifactFamily)
                else ArtifactFamily(str(request.artifact_family_hint))
            )

        families = [f.value for f in ArtifactFamily if f != ArtifactFamily.custom]
        prompt = (
            f"User request: \"{request.user_query}\"\n\n"
            f"What type of deliverable is the user asking for?\n\n"
            f"Options:\n"
            f"- pitch_deck: slide presentations, pitch decks, decks\n"
            f"- poster: posters, event posters\n"
            f"- report: reports, analysis documents\n"
            f"- finance_analysis: financial analysis, investment research, equity\n"
            f"- email: emails, cold emails, follow-up emails, newsletters\n"
            f"- invoice: invoices, billing, receipts\n"
            f"- letter: letters, formal letters, cover letters\n"
            f"- memo: memos, internal memos\n"
            f"- proposal: proposals, business proposals, RFP responses\n"
            f"- social_post: social media posts, LinkedIn posts, tweets, Instagram posts\n"
            f"- summary: summaries, executive summaries, briefs\n"
            f"- keynote: keynotes, stage presentations\n"
            f"- brochure: brochures, booklets\n"
            f"- one_pager: one-pagers, brief documents\n"
            f"- landing_page: landing pages, web pages\n\n"
            f"Return ONLY JSON: {{\"family\": \"<option>\", \"confidence\": 0.0-1.0}}"
        )
        try:
            response = await self.resolver.acompletion(
                "routing",
                [
                    {"role": "system", "content": "You are an artifact type classifier. Return only JSON. No explanation."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=60,
                temperature=0.0,
            )
            raw = self.resolver.extract_text(response)
            parsed = self.resolver.safe_json_loads(raw)
            family_str = str(parsed.get("family", "")).strip().lower()
            confidence = float(parsed.get("confidence", 0.0))
            if confidence >= 0.5:
                try:
                    result = ArtifactFamily(family_str)
                    await self.log(
                        f"LLM artifact classification: {result.value} (confidence {confidence:.2f})",
                        kind="decision", visibility="debug",
                    )
                    return result
                except ValueError:
                    pass
            # Low confidence — log and fall through
            await self.log(
                f"LLM artifact classification low confidence ({confidence:.2f}), using heuristic: {fallback.value}",
                kind="decision", visibility="debug",
            )
        except Exception as exc:
            await self.log(
                f"LLM artifact classification failed ({exc}), using heuristic: {fallback.value}",
                kind="status", visibility="debug",
            )
        return fallback

    @staticmethod
    def derive_artifact_requirements(family: ArtifactFamily, request_payload: dict[str, object] | SubmitWorkflowRequest) -> RequirementsChecklist:
        if isinstance(request_payload, SubmitWorkflowRequest):
            values = {
                "target_audience": request_payload.target_audience,
                "delivery_channel": request_payload.delivery_channel,
                "brand_context": request_payload.brand_context,
                "analysis_subject": request_payload.analysis_subject,
                "analysis_objective": request_payload.analysis_objective,
                "analysis_horizon": request_payload.analysis_horizon,
                "analysis_benchmark": request_payload.analysis_benchmark,
                "must_have_sections": request_payload.must_have_sections,
                "explicit_requirements": request_payload.explicit_requirements,
            }
            user_query = request_payload.user_query
        else:
            values = {
                "target_audience": request_payload.get("target_audience"),
                "delivery_channel": request_payload.get("delivery_channel"),
                "brand_context": request_payload.get("brand_context"),
                "analysis_subject": request_payload.get("analysis_subject"),
                "analysis_objective": request_payload.get("analysis_objective"),
                "analysis_horizon": request_payload.get("analysis_horizon"),
                "analysis_benchmark": request_payload.get("analysis_benchmark"),
                "must_have_sections": request_payload.get("must_have_sections", []),
                "explicit_requirements": request_payload.get("explicit_requirements", []),
            }
            user_query = str(request_payload.get("user_query", ""))

        if family == ArtifactFamily.finance_analysis:
            values = dict(values)
            if not values.get("analysis_subject"):
                values["analysis_subject"] = user_query or "the selected company or asset"
            if not values.get("analysis_objective"):
                values["analysis_objective"] = "Assess the financial performance and produce a recommendation."
            if not values.get("analysis_horizon"):
                values["analysis_horizon"] = "next 12 months"
            if not values.get("analysis_benchmark"):
                values["analysis_benchmark"] = "relevant sector peers"

        blueprint = ARTIFACT_BLUEPRINTS[family]
        items: list[RequirementItem] = []
        missing_ids: list[str] = []
        for index, section in enumerate(blueprint["required_sections"], start=1):
            requirement_id = f"section:{str(section).lower().replace(' ', '_')}"
            must_have = True
            if family == ArtifactFamily.finance_analysis:
                status = "filled"
            else:
                status = "filled" if str(section).lower() in {str(item).lower() for item in values["must_have_sections"]} else "pending"
            if status == "pending":
                missing_ids.append(requirement_id)
            items.append(
                RequirementItem(
                    requirement_id=requirement_id,
                    text=f"Provide the {section} for the {family.value} artifact.",
                    category="section",
                    source="artifact_family",
                    priority=index,
                    must_have=must_have,
                    owner_task_id="content_director" if section else None,
                    status=status,
                    blockers=[],
                    blocking_stage=RequirementStage.evidence_informed,
                )
            )

        for field_name in blueprint["blocking_fields"]:
            value = values.get(field_name)
            requirement_id = f"field:{field_name}"
            status = "filled" if value else "pending"
            if status == "pending":
                missing_ids.append(requirement_id)
            items.append(
                RequirementItem(
                    requirement_id=requirement_id,
                    text=f"Collect {field_name.replace('_', ' ')}.",
                    category="clarification",
                    source="hitl",
                    priority=0,
                    must_have=True,
                    owner_task_id="hitl",
                    status=status,
                    blocking_stage=RequirementStage.before_render,
                )
            )

        for field_name in blueprint.get("evidence_informed_fields", []):
            value = values.get(field_name)
            requirement_id = f"field:{field_name}"
            normalized_value = value if not isinstance(value, list) else [str(item).strip() for item in value if str(item).strip()]
            status = "filled" if normalized_value else "pending"
            if status == "pending":
                missing_ids.append(requirement_id)
            items.append(
                RequirementItem(
                    requirement_id=requirement_id,
                    text=f"Collect {field_name.replace('_', ' ')} after research context is available.",
                    category="clarification",
                    source="hitl",
                    priority=1,
                    must_have=True,
                    owner_task_id="hitl_evidence",
                    status=status,
                    blocking_stage=RequirementStage.evidence_informed,
                )
            )

        for index, requirement in enumerate(values["explicit_requirements"], start=1):
            requirement_id = f"explicit:{index}"
            items.append(
                RequirementItem(
                    requirement_id=requirement_id,
                    text=str(requirement),
                    category="explicit",
                    source="user",
                    priority=10 + index,
                    must_have=True,
                    owner_task_id="content_director",
                    status="pending",
                    blocking_stage=RequirementStage.before_render,
                )
            )
            missing_ids.append(requirement_id)

        coverage = 1.0 if items and not missing_ids else max(0.0, 1.0 - (len(missing_ids) / max(len(items), 1)))
        return RequirementsChecklist(items=items, coverage_score=coverage, missing_required_ids=sorted(set(missing_ids)))

    @staticmethod
    def compute_missing_requirements(checklist: RequirementsChecklist) -> RequirementsChecklist:
        missing = [item.requirement_id for item in checklist.items if item.must_have and item.status != "filled"]
        coverage = 1.0 if checklist.items and not missing else max(0.0, 1.0 - (len(missing) / max(len(checklist.items), 1)))
        return checklist.model_copy(update={"coverage_score": coverage, "missing_required_ids": sorted(set(missing))})

    def match_agents_for_task_role(self, task_role: TaskRole, agent_catalog: list[LiveAgentProfile]) -> list[dict[str, object]]:
        matches: list[dict[str, object]] = []
        for agent in agent_catalog:
            if agent.status == AgentStatus.disabled:
                continue
            capability_names = {cap.name.lower() for cap in agent.capabilities}
            if task_role == TaskRole.hitl:
                continue
            if task_role == TaskRole.content_director and not any(name in capability_names for name in {"content_distribution", "section_planning"}):
                continue
            if task_role == TaskRole.research and not any(name in capability_names for name in {"web_research", "document_research", "memory_retrieval", "memory_synthesis"}):
                continue
            if task_role == TaskRole.vangogh and not any(name in capability_names for name in {"artifact_layout", "html_css_composition"}):
                continue
            if task_role == TaskRole.governance and "artifact_validation" not in capability_names:
                continue
            matches.append(
                {
                    "agent_name": agent.name,
                    "role": agent.role,
                    "status": agent.status.value,
                    "current_load": agent.current_load,
                    "capabilities": [cap.name for cap in agent.capabilities],
                    "skills": [skill.name for skill in agent.skills],
                }
            )
        return matches

    def compose_task_graph(
        self,
        family: ArtifactFamily,
        requirements: RequirementsChecklist,
        agent_catalog: list[LiveAgentProfile],
    ) -> TaskGraph:
        web_agent, docs_agent = self._assign_research_agents(agent_catalog)
        content_director_agent = self._assign_role_agent(agent_catalog, "content_distribution", "content_director")
        design_agent = self._assign_role_agent(agent_catalog, "artifact_layout", "vangogh")
        governance_agent = self._assign_role_agent(agent_catalog, "artifact_validation", "governance")
        needs_evidence_hitl = any(
            item.must_have and item.status != "filled" and item.blocking_stage in {RequirementStage.evidence_informed, RequirementStage.before_render}
            for item in requirements.items
        )

        nodes: list[WorkflowNode] = [
            WorkflowNode(
                node_id="research-web",
                task_role=TaskRole.research,
                executor_kind=ExecutorKind.agent,
                purpose="Research web evidence",
                parallel_group="research",
                outputs={"evidence_type": "web"},
                required_capabilities=["web_research"],
                assigned_to=web_agent,
            ),
            WorkflowNode(
                node_id="research-docs",
                task_role=TaskRole.research,
                executor_kind=ExecutorKind.agent,
                purpose="Research uploaded docs",
                parallel_group="research",
                outputs={"evidence_type": "docs"},
                required_capabilities=["document_research"],
                assigned_to=docs_agent,
            ),
        ]
        if needs_evidence_hitl:
            nodes.append(
                WorkflowNode(
                    node_id="hitl_evidence",
                    task_role=TaskRole.hitl,
                    executor_kind=ExecutorKind.human,
                    purpose="Resolve evidence-informed gaps before rendering",
                    depends_on=["research-web", "research-docs"],
                    inputs={
                        "missing_requirements": [
                            item.requirement_id
                            for item in requirements.items
                            if item.must_have and item.status != "filled" and item.blocking_stage in {RequirementStage.evidence_informed, RequirementStage.before_render}
                        ]
                    },
                    acceptance_criteria=["Evidence-aware user answers collected"],
                    requires_approval=True,
                    assigned_to="user",
                )
            )
        nodes.extend(
            [
                WorkflowNode(
                    node_id="content_director",
                    task_role=TaskRole.content_director,
                    executor_kind=ExecutorKind.agent,
                    purpose="Turn requirements and evidence into a content distribution brief",
                    depends_on=["research-web", "research-docs"]
                    + (["hitl_evidence"] if needs_evidence_hitl else []),
                    inputs={"artifact_family": family.value},
                    outputs={"content_brief": True},
                    required_capabilities=["content_distribution", "section_planning"],
                    assigned_to=content_director_agent,
                ),
                WorkflowNode(
                    node_id="vangogh",
                    task_role=TaskRole.vangogh,
                    executor_kind=ExecutorKind.agent,
                    purpose="Render the final visual artifact",
                    depends_on=["content_director"],
                    inputs={"artifact_family": family.value},
                    outputs={"artifact": True},
                    required_capabilities=["artifact_layout", "html_css_composition"],
                    assigned_to=design_agent,
                ),
                WorkflowNode(
                    node_id="governance",
                    task_role=TaskRole.governance,
                    executor_kind=ExecutorKind.agent,
                    purpose="Validate the final artifact",
                    depends_on=["vangogh"],
                    inputs={"artifact_family": family.value},
                    outputs={"governance_report": True},
                    required_capabilities=["artifact_validation"],
                    assigned_to=governance_agent,
                    requires_approval=True,
                ),
            ]
        )

        edges = [
            WorkflowEdge(from_node="research-web", to_node="content_director"),
            WorkflowEdge(from_node="research-docs", to_node="content_director"),
            WorkflowEdge(from_node="content_director", to_node="vangogh"),
            WorkflowEdge(from_node="vangogh", to_node="governance"),
        ]
        if needs_evidence_hitl:
            edges.extend(
                [
                    WorkflowEdge(from_node="research-web", to_node="hitl_evidence"),
                    WorkflowEdge(from_node="research-docs", to_node="hitl_evidence"),
                    WorkflowEdge(from_node="hitl_evidence", to_node="content_director"),
                ]
            )
        return TaskGraph(
            nodes=nodes,
            edges=edges,
            entry_nodes=["research-web", "research-docs"],
            terminal_nodes=["governance"],
            fan_in_groups=["research"],
        )

    def compose_text_task_graph(
        self,
        family: ArtifactFamily,
        requirements: RequirementsChecklist,
        agent_catalog: list[LiveAgentProfile],
    ) -> TaskGraph:
        """Build a task graph for text-based artifacts: research → [hitl] → text_buddy → governance."""
        web_agent, docs_agent = self._assign_research_agents(agent_catalog)
        text_buddy_agent = self._assign_role_agent(
            agent_catalog, "text_composition", "text_buddy",
            artifact_family=family.value,
        )
        governance_agent = self._assign_role_agent(agent_catalog, "artifact_validation", "governance")
        needs_evidence_hitl = any(
            item.must_have and item.status != "filled" and item.blocking_stage in {RequirementStage.evidence_informed, RequirementStage.before_render}
            for item in requirements.items
        )

        nodes: list[WorkflowNode] = [
            WorkflowNode(
                node_id="research-web",
                task_role=TaskRole.research,
                executor_kind=ExecutorKind.agent,
                purpose="Research web evidence",
                parallel_group="research",
                outputs={"evidence_type": "web"},
                required_capabilities=["web_research"],
                assigned_to=web_agent,
            ),
            WorkflowNode(
                node_id="research-docs",
                task_role=TaskRole.research,
                executor_kind=ExecutorKind.agent,
                purpose="Research uploaded docs",
                parallel_group="research",
                outputs={"evidence_type": "docs"},
                required_capabilities=["document_research"],
                assigned_to=docs_agent,
            ),
        ]
        if needs_evidence_hitl:
            nodes.append(
                WorkflowNode(
                    node_id="hitl_evidence",
                    task_role=TaskRole.hitl,
                    executor_kind=ExecutorKind.human,
                    purpose="Resolve evidence-informed gaps before writing",
                    depends_on=["research-web", "research-docs"],
                    inputs={
                        "missing_requirements": [
                            item.requirement_id
                            for item in requirements.items
                            if item.must_have and item.status != "filled" and item.blocking_stage in {RequirementStage.evidence_informed, RequirementStage.before_render}
                        ]
                    },
                    acceptance_criteria=["Evidence-aware user answers collected"],
                    requires_approval=True,
                    assigned_to="user",
                )
            )
        nodes.extend(
            [
                WorkflowNode(
                    node_id="text_buddy",
                    task_role=TaskRole.text_buddy,
                    executor_kind=ExecutorKind.agent,
                    purpose="Compose final text content in brand voice",
                    depends_on=["research-web", "research-docs"]
                    + (["hitl_evidence"] if needs_evidence_hitl else []),
                    inputs={"artifact_family": family.value},
                    outputs={"text_artifact": True},
                    required_capabilities=["text_composition", "brand_voice_writing"],
                    assigned_to=text_buddy_agent,
                ),
                WorkflowNode(
                    node_id="governance",
                    task_role=TaskRole.governance,
                    executor_kind=ExecutorKind.agent,
                    purpose="Validate the final text artifact",
                    depends_on=["text_buddy"],
                    inputs={"artifact_family": family.value},
                    outputs={"governance_report": True},
                    required_capabilities=["artifact_validation"],
                    assigned_to=governance_agent,
                    requires_approval=True,
                ),
            ]
        )

        edges = [
            WorkflowEdge(from_node="research-web", to_node="text_buddy"),
            WorkflowEdge(from_node="research-docs", to_node="text_buddy"),
            WorkflowEdge(from_node="text_buddy", to_node="governance"),
        ]
        if needs_evidence_hitl:
            edges.extend(
                [
                    WorkflowEdge(from_node="research-web", to_node="hitl_evidence"),
                    WorkflowEdge(from_node="research-docs", to_node="hitl_evidence"),
                    WorkflowEdge(from_node="hitl_evidence", to_node="text_buddy"),
                ]
            )
        return TaskGraph(
            nodes=nodes,
            edges=edges,
            entry_nodes=["research-web", "research-docs"],
            terminal_nodes=["governance"],
            fan_in_groups=["research"],
        )

    @staticmethod
    def _infer_catalog_summary(agent_catalog: list[LiveAgentProfile]) -> dict[str, list[str]]:
        summary: dict[str, list[str]] = {"research": [], "design": [], "review": [], "strategy": []}
        for agent in agent_catalog:
            caps = {cap.name for cap in agent.capabilities}
            if any(name in caps for name in {"web_research", "document_research"}):
                summary["research"].append(agent.name)
            if any(name in caps for name in {"artifact_layout", "html_css_composition"}):
                summary["design"].append(agent.name)
            if "artifact_validation" in caps:
                summary["review"].append(agent.name)
            if any(name in caps for name in {"route_planning", "task_graph_authoring"}):
                summary["strategy"].append(agent.name)
        return summary

    @staticmethod
    def _heuristic_topology(request: SubmitWorkflowRequest, agent_catalog: list[LiveAgentProfile]) -> WorkflowMode:
        query = request.user_query.lower()
        summary = StrategicAgent._infer_catalog_summary(agent_catalog)
        research_agents = summary["research"]
        design_agents = summary["design"]
        review_agents = summary["review"]
        full_core_present = bool(research_agents and design_agents and review_agents)
        parallel_ready = len(research_agents) >= 2

        if request.workflow_mode != WorkflowMode.hybrid:
            return request.workflow_mode
        if not full_core_present:
            return WorkflowMode.sequential
        if parallel_ready or request.source_scope == "web_and_docs":
            return WorkflowMode.hybrid
        if any(keyword in query for keyword in ("compare", "analyze", "research", "multi", "parallel", "several", "multiple")):
            return WorkflowMode.parallel
        return WorkflowMode.sequential

    async def choose_topology(self, request: SubmitWorkflowRequest, agent_catalog: list[LiveAgentProfile]) -> WorkflowMode:
        # await self.log("Analyzing your request against the live agent catalog to determine workflow topology.", kind="thought")
        # await self.log(
        #     "Inspecting request shape, artifact family, and available live agents before selecting a topology.",
        #     kind="thought",
        #     detail={
        #         "requested_mode": request.workflow_mode.value,
        #         "artifact_type": request.artifact_type,
        #         "source_scope": request.source_scope,
        #         "live_agent_count": len(agent_catalog),
        #     },
        # )
        mode = self._heuristic_topology(request, agent_catalog)
        # await self.log(
        #     f"Selected '{mode.value}' topology from the live catalog.",
        #     kind="decision",
        #     detail={
        #         "workflow_mode": mode.value,
        #         "reasoning": "Immediate catalog-aware heuristic selection.",
        #         "topology_reason": "Topology chosen from live agent availability, request shape, and source scope without waiting on a model round-trip.",
        #     },
        # )
        return mode

    def _assign_research_agents(self, agent_catalog: list[LiveAgentProfile]) -> tuple[str, str]:
        web_agent = "research"
        docs_agent = "research"
        for agent in agent_catalog:
            capability_names = {cap.name for cap in agent.capabilities}
            if "web_research" in capability_names and web_agent == "research":
                web_agent = agent.name
            if "document_research" in capability_names and docs_agent == "research":
                docs_agent = agent.name
        return web_agent, docs_agent

    @staticmethod
    def _assign_role_agent(
        agent_catalog: list[LiveAgentProfile],
        capability_name: str,
        default_agent: str,
        *,
        artifact_family: str | None = None,
    ) -> str:
        """Assign the best agent for a role using the scored resolver.

        Delegates to contracts.resolver.resolve_agent which scores by:
        role match -> capabilities -> tools -> artifact affinity -> custom preference.
        """
        from agentscope_blaiq.contracts.resolver import resolve_agent

        result = resolve_agent(
            agent_catalog,
            required_role=default_agent,  # default_agent IS the role for built-ins
            required_capabilities=[capability_name] if capability_name else None,
            artifact_family=artifact_family,
            default_agent=default_agent,
        )
        return result.selected

    def _compose_assignments(self, mode: WorkflowMode, agent_catalog: list[LiveAgentProfile]) -> list[AgentTaskAssignment]:
        web_agent, docs_agent = self._assign_research_agents(agent_catalog)
        content_director_agent = self._assign_role_agent(agent_catalog, "content_distribution", "content_director")
        design_agent = self._assign_role_agent(agent_catalog, "artifact_layout", "vangogh")
        governance_agent = self._assign_role_agent(agent_catalog, "artifact_validation", "governance")

        if mode == WorkflowMode.sequential:
            return [
                AgentTaskAssignment(
                    task_id="research-web",
                    agent_name=web_agent,
                    role="research",
                    reason="Sequential research requires the best available research agent.",
                    required_capabilities=["web_research", "document_research"],
                    task_role=TaskRole.research.value,
                    executor_kind=ExecutorKind.agent.value,
                    task_graph_node_id="research-web",
                ),
                AgentTaskAssignment(
                    task_id="content_director",
                    agent_name=content_director_agent,
                    role="content_director",
                    reason="Content direction follows the completed research step.",
                    required_capabilities=["content_distribution", "section_planning"],
                    task_role=TaskRole.content_director.value,
                    executor_kind=ExecutorKind.agent.value,
                    task_graph_node_id="content_director",
                ),
                AgentTaskAssignment(
                    task_id="artifact",
                    agent_name=design_agent,
                    role="vangogh",
                    reason="Artifact generation follows the completed research step.",
                    required_capabilities=["artifact_layout", "html_css_composition"],
                    task_role=TaskRole.vangogh.value,
                    executor_kind=ExecutorKind.agent.value,
                    task_graph_node_id="vangogh",
                ),
                AgentTaskAssignment(
                    task_id="governance",
                    agent_name=governance_agent,
                    role="governance",
                    reason="Validation closes the sequential workflow.",
                    required_capabilities=["artifact_validation"],
                    task_role=TaskRole.governance.value,
                    executor_kind=ExecutorKind.agent.value,
                    task_graph_node_id="governance",
                ),
            ]

        if mode == WorkflowMode.parallel:
            return [
                AgentTaskAssignment(
                    task_id="research-web",
                    agent_name=web_agent,
                    role="research",
                    parallel_group="research",
                    reason="Assigned to the web-capable research agent.",
                    required_capabilities=["web_research"],
                    task_role=TaskRole.research.value,
                    executor_kind=ExecutorKind.agent.value,
                    task_graph_node_id="research-web",
                ),
                AgentTaskAssignment(
                    task_id="research-docs",
                    agent_name=docs_agent,
                    role="research",
                    parallel_group="research",
                    reason="Assigned to the document-capable research agent.",
                    required_capabilities=["document_research"],
                    task_role=TaskRole.research.value,
                    executor_kind=ExecutorKind.agent.value,
                    task_graph_node_id="research-docs",
                ),
                AgentTaskAssignment(
                    task_id="content_director",
                    agent_name=content_director_agent,
                    role="content_director",
                    reason="Content direction follows fan-in.",
                    required_capabilities=["content_distribution", "section_planning"],
                    task_role=TaskRole.content_director.value,
                    executor_kind=ExecutorKind.agent.value,
                    task_graph_node_id="content_director",
                ),
                AgentTaskAssignment(
                    task_id="artifact",
                    agent_name=design_agent,
                    role="vangogh",
                    parallel_group="artifact",
                    reason="Artifact generation happens after fan-in.",
                    required_capabilities=["artifact_layout", "html_css_composition"],
                    task_role=TaskRole.vangogh.value,
                    executor_kind=ExecutorKind.agent.value,
                    task_graph_node_id="vangogh",
                ),
                AgentTaskAssignment(
                    task_id="governance",
                    agent_name=governance_agent,
                    role="governance",
                    reason="Validation is the final gate.",
                    required_capabilities=["artifact_validation"],
                    task_role=TaskRole.governance.value,
                    executor_kind=ExecutorKind.agent.value,
                    task_graph_node_id="governance",
                ),
            ]

        return [
            AgentTaskAssignment(
                task_id="research-web",
                agent_name=web_agent,
                role="research",
                parallel_group="research",
                reason="Web evidence can run in parallel.",
                required_capabilities=["web_research"],
                task_role=TaskRole.research.value,
                executor_kind=ExecutorKind.agent.value,
                task_graph_node_id="research-web",
            ),
            AgentTaskAssignment(
                task_id="research-docs",
                agent_name=docs_agent,
                role="research",
                parallel_group="research",
                reason="Document evidence can run in parallel.",
                required_capabilities=["document_research"],
                task_role=TaskRole.research.value,
                executor_kind=ExecutorKind.agent.value,
                task_graph_node_id="research-docs",
            ),
            AgentTaskAssignment(
                task_id="content_director",
                agent_name=content_director_agent,
                role="content_director",
                reason="Content direction turns evidence into a page plan.",
                required_capabilities=["content_distribution", "section_planning"],
                task_role=TaskRole.content_director.value,
                executor_kind=ExecutorKind.agent.value,
                task_graph_node_id="content_director",
            ),
            AgentTaskAssignment(
                task_id="artifact",
                agent_name=design_agent,
                role="vangogh",
                reason="Artifact generation consumes merged evidence.",
                required_capabilities=["artifact_layout", "html_css_composition"],
                task_role=TaskRole.vangogh.value,
                executor_kind=ExecutorKind.agent.value,
                task_graph_node_id="vangogh",
            ),
            AgentTaskAssignment(
                task_id="governance",
                agent_name=governance_agent,
                role="governance",
                reason="Validation closes the hybrid workflow.",
                required_capabilities=["artifact_validation"],
                task_role=TaskRole.governance.value,
                executor_kind=ExecutorKind.agent.value,
                task_graph_node_id="governance",
            ),
        ]

    async def _build_strategy_draft(
        self,
        request: SubmitWorkflowRequest,
        mode: WorkflowMode,
        task_count: int,
        *,
        agent_catalog: list[LiveAgentProfile],
        assignments: list[AgentTaskAssignment],
        artifact_family: ArtifactFamily | None = None,
    ) -> StrategicDraft:
        # await self.log(f"Building execution strategy for {task_count} tasks in '{mode.value}' mode.", kind="thought")
        finance_mode = request.analysis_mode == AnalysisMode.finance
        research_agents = [agent.name for agent in agent_catalog if any(cap.name in {"web_research", "document_research"} for cap in agent.capabilities)]
        content_agents = [agent.name for agent in agent_catalog if any(cap.name in {"content_distribution", "section_planning"} for cap in agent.capabilities)]
        design_agents = [agent.name for agent in agent_catalog if any(cap.name in {"artifact_layout", "html_css_composition"} for cap in agent.capabilities)]
        review_agents = [agent.name for agent in agent_catalog if any(cap.name == "artifact_validation" for cap in agent.capabilities)]
        assignment_names = [assignment.agent_name for assignment in assignments]

        text_buddy_agents = [agent.name for agent in agent_catalog if any(cap.name in {"text_composition", "brand_voice_writing"} for cap in agent.capabilities)]
        _family = artifact_family or self.classify_artifact_family(request)
        is_text_family = _family in TEXT_FAMILIES

        if finance_mode:
            summary = (
                f"The finance workflow starts with {'parallel research' if mode != WorkflowMode.sequential else 'a sequential research pass'} "
                f"to form hypotheses, gather evidence from HIVE-MIND memory, uploaded documents, and live sources, and then separates evidence from interpretation "
                f"before {content_agents[0] if content_agents else 'the content director'} turns the brief into a traceable report plan, "
                f"{design_agents[0] if design_agents else 'Vangogh'} renders the report, and {review_agents[0] if review_agents else 'Governance'} validates the result."
            )
        elif is_text_family:
            summary = (
                f"The strategy starts with {'parallel research' if mode != WorkflowMode.sequential else 'a sequential research pass'} "
                f"to ground the request in HIVE-MIND memory, uploaded sources, and freshness checks when needed. "
                f"Then {text_buddy_agents[0] if text_buddy_agents else 'TextBuddy'} composes the final {artifact_family.value.replace('_', ' ')} "
                f"in brand voice with evidence citations, and {review_agents[0] if review_agents else 'Governance'} validates the result."
            )
        else:
            summary = (
                f"The strategy starts with {'parallel research' if mode != WorkflowMode.sequential else 'a sequential research pass'} "
                f"to ground the request in HIVE-MIND memory, uploaded sources, and freshness checks when needed. It then uses {content_agents[0] if content_agents else 'the content director'} "
                f"to translate the brief into section-level guidance before {design_agents[0] if design_agents else 'Vangogh'} renders the final artifact "
                f"and {review_agents[0] if review_agents else 'Governance'} validates the result."
            )
        notes = [
            f"Live catalog agents considered: {', '.join(research_agents + content_agents + design_agents + text_buddy_agents + review_agents) or 'none'}.",
            f"Assignments resolved: {', '.join(assignment_names) or 'none'}.",
            "The workflow prefers research before clarification so follow-up questions can be shaped by evidence instead of guesswork.",
        ]
        if finance_mode:
            notes.append("Finance mode keeps a hypothesis-driven evidence chain and writes the final analysis as a report instead of a pitch deck.")
        draft = StrategicDraft(
            workflow_mode=mode,
            summary=summary,
            notes=notes,
            task_count=task_count,
            topology_reason="Deterministic strategy draft derived from the live agent catalog and artifact requirements.",
        )
        await self.log(summary, kind="status")
        return draft

    @staticmethod
    def _workflow_template_id_for(
        artifact_family: ArtifactFamily,
        analysis_mode: AnalysisMode,
        *,
        direct_answer: bool = False,
    ) -> str:
        if direct_answer:
            return "direct_answer_v1"
        if analysis_mode == AnalysisMode.finance or artifact_family == ArtifactFamily.finance_analysis:
            return "finance_v1"
        if artifact_family in TEXT_FAMILIES:
            return "text_artifact_v1"
        return "visual_artifact_v1"

    @staticmethod
    def _node_assignments(task_graph: TaskGraph) -> dict[str, str]:
        return {
            node.node_id: node.assigned_to
            for node in task_graph.nodes
            if node.executor_kind == ExecutorKind.agent and node.assigned_to
        }

    @staticmethod
    def _required_tools_per_node(
        task_graph: TaskGraph,
        agent_catalog: list[LiveAgentProfile],
    ) -> dict[str, list[str]]:
        tools_by_agent = {agent.name: list(agent.tools) for agent in agent_catalog}
        return {
            node.node_id: tools_by_agent.get(node.assigned_to or "", [])
            for node in task_graph.nodes
            if node.executor_kind == ExecutorKind.agent and node.assigned_to
        }

    async def fan_in(self, evidence_packs: list[dict]) -> dict:
        # await self.log(f"Merging {len(evidence_packs)} evidence packs into a consolidated brief.", kind="status")
        result = {
            "summary": f"Merged {len(evidence_packs)} evidence packs.",
            "evidence_packs": evidence_packs,
        }
        # await self.log("Evidence merge complete. Ready for artifact generation.", kind="status")
        return result

    async def build_plan(
        self,
        request: SubmitWorkflowRequest,
        agent_catalog: list[LiveAgentProfile] | None = None,
        user_registry: Any | None = None,
    ) -> WorkflowPlan:
        catalog = agent_catalog if agent_catalog is not None else self.catalog_provider()
        route = await self.classify_route_llm(request)

        # ── Conversational: no research, no HITL, respond directly ──
        if route == "conversational":
            await self.log(
                "Detected a conversational message. Responding directly without research.",
                kind="decision",
            )
            return WorkflowPlan(
                workflow_mode=WorkflowMode.sequential,
                summary="Conversational response — no research or artifact workflow needed.",
                direct_answer=True,
                conversational=True,
                notes=["Route chosen: conversational, skipping research and HITL."],
                artifact_family=ArtifactFamily.custom,
                artifact_spec=ArtifactSpec(
                    family=ArtifactFamily.custom,
                    title=request.user_query,
                    audience=request.target_audience,
                    deliverable_format="text_answer",
                    required_sections=[],
                    tone="friendly",
                    constraints=[],
                    success_criteria=["Friendly conversational response"],
                ),
                requirements_checklist=RequirementsChecklist(items=[], coverage_score=1.0, missing_required_ids=[]),
                task_graph=TaskGraph(nodes=[], edges=[], entry_nodes=[], terminal_nodes=[]),
                tasks=[],
                available_agents=[p for p in catalog],
                workflow_template_id="direct_answer_v1",
            )

        # ── Direct answer: research + synthesize, skip artifact pipeline ──
        if route == "direct_answer":
            await self.log(
                "Detected a direct knowledge question. Routing straight to memory-first research and a final synthesized answer.",
                kind="decision",
            )
            research_node = WorkflowNode(
                node_id="research-answer",
                task_role=TaskRole.research,
                executor_kind=ExecutorKind.agent,
                purpose="Research the question with HIVE-MIND recall first, then synthesize a direct answer.",
                assigned_to="research",
                required_capabilities=["memory_retrieval", "memory_synthesis"],
                inputs={"response_mode": "direct_answer"},
            )
            task_graph = TaskGraph(
                nodes=[research_node],
                edges=[],
                entry_nodes=["research-answer"],
                terminal_nodes=["research-answer"],
            )
            task = AgentRunPayload(
                agent_type=AgentType.research,
                purpose=research_node.purpose,
                node_id=research_node.node_id,
                task_role=research_node.task_role,
                executor_kind=research_node.executor_kind,
                inputs=research_node.inputs,
                required_capabilities=research_node.required_capabilities,
                assigned_to=research_node.assigned_to,
            )
            summary = (
                "This is a direct knowledge question, so I will skip artifact generation, run HIVE-MIND-first research, "
                "and return a synthesized answer."
            )
            notes = [
                "Route chosen: direct answer, not artifact workflow.",
                "Research still prefers HIVE-MIND memory before any live web fallback.",
            ]
            return WorkflowPlan(
                workflow_mode=WorkflowMode.sequential,
                summary=summary,
                direct_answer=True,
                notes=notes,
                artifact_family=ArtifactFamily.custom,
                artifact_spec=ArtifactSpec(
                    family=ArtifactFamily.custom,
                    title=request.user_query,
                    audience=request.target_audience,
                    deliverable_format="text_answer",
                    required_sections=[],
                    tone="direct",
                    constraints=[],
                    success_criteria=["Research uses HIVE-MIND recall first", "Final answer is concise and evidence-backed"],
                ),
                requirements_checklist=RequirementsChecklist(items=[], coverage_score=1.0, missing_required_ids=[]),
                task_graph=task_graph,
                tasks=[task],
                hitl_nodes=[],
                content_director_nodes=[],
                available_agents=catalog,
                agent_assignments=self._compose_assignments(WorkflowMode.sequential, catalog),
                topology_reason="Direct knowledge query routed to research-only answer path.",
                fan_in_required=False,
                analysis_mode=request.analysis_mode,
            )
        # LLM-first classification; heuristic only if LLM fails
        artifact_family = await self._classify_artifact_family_llm(
            request, self.classify_artifact_family(request),
        )
        analysis_mode = request.analysis_mode
        finance_mode = analysis_mode == AnalysisMode.finance or artifact_family == ArtifactFamily.finance_analysis
        artifact_spec = ArtifactSpec(
            family=artifact_family,
            title=request.user_query,
            audience=request.target_audience,
            deliverable_format=request.artifact_type,
            required_sections=list(ARTIFACT_BLUEPRINTS[artifact_family]["required_sections"]),
            tone=str(ARTIFACT_BLUEPRINTS[artifact_family]["tone"]),
            constraints=[str(constraint) for constraint in request.explicit_requirements],
            success_criteria=(
                [
                    "The analysis states a clear thesis and hypothesis chain",
                    "Evidence is grounded in HIVE-MIND memory, uploaded docs, and live sources",
                    "The final report separates evidence from interpretation",
                    "Governance validates that claims remain source-backed",
                ]
                if finance_mode
                else [
                    "Strategy acknowledges the live catalog",
                    "Research is grounded in sources",
                    "Content director produces a section plan",
                    "Vangogh renders the final artifact",
                ]
            ),
        )
        requirements = self.compute_missing_requirements(
            self.derive_artifact_requirements(artifact_family, request)
        )
        mode = await self.choose_topology(request, catalog)
        if artifact_family != ArtifactFamily.custom:
            mode = WorkflowMode.hybrid if mode == WorkflowMode.hybrid else mode
        assignments = self._compose_assignments(mode, catalog)
        if artifact_family in TEXT_FAMILIES:
            task_graph = self.compose_text_task_graph(artifact_family, requirements, catalog)
            topology_reason = (
                f"Planner matched the request to the {artifact_family.value} text artifact family and selected a {mode.value} topology: research → text_buddy → governance (text pipeline)."
            )
        else:
            task_graph = self.compose_task_graph(artifact_family, requirements, catalog)
            topology_reason = (
                f"Planner matched the request to the {artifact_family.value} artifact family and selected a {mode.value} topology so research can fan out before content direction, rendering, and governance converge."
            )

        def node_to_task(node: WorkflowNode) -> AgentRunPayload | None:
            if node.executor_kind == ExecutorKind.human:
                return None
            return AgentRunPayload(
                agent_type=TASK_ROLE_TO_AGENT_TYPE.get(node.task_role, AgentType.strategist),
                purpose=node.purpose,
                depends_on=list(node.depends_on),
                branch_key=node.parallel_group,
                task_input={
                    "artifact_family": artifact_family.value,
                    "inputs": node.inputs,
                    "outputs": node.outputs,
                    "acceptance_criteria": node.acceptance_criteria,
                },
                node_id=node.node_id,
                task_role=node.task_role,
                executor_kind=node.executor_kind,
                parallel_group=node.parallel_group,
                inputs=node.inputs,
                outputs=node.outputs,
                acceptance_criteria=node.acceptance_criteria,
                requires_approval=node.requires_approval,
                assigned_to=node.assigned_to,
                required_capabilities=node.required_capabilities,
            )

        tasks = [task for node in task_graph.nodes if (task := node_to_task(node)) is not None]
        hitl_nodes = [node for node in task_graph.nodes if node.task_role == TaskRole.hitl]
        content_director_nodes = [node for node in task_graph.nodes if node.task_role == TaskRole.content_director]
        draft = await self._build_strategy_draft(
            request,
            mode,
            len(tasks),
            agent_catalog=catalog,
            assignments=assignments,
            artifact_family=artifact_family,
        )
        draft = draft.model_copy(
            update={
                "artifact_family": artifact_family,
                "artifact_spec": artifact_spec,
                "requirements_checklist": requirements,
                "task_graph": task_graph,
                "hitl_nodes": hitl_nodes,
                "content_director_nodes": content_director_nodes,
                "topology_reason": topology_reason,
                "analysis_mode": analysis_mode,
                "workflow_template_id": self._workflow_template_id_for(
                    artifact_family,
                    analysis_mode,
                ),
                "node_assignments": self._node_assignments(task_graph),
                "required_tools_per_node": self._required_tools_per_node(task_graph, catalog),
                "fallback_path": "replan_from_strategist",
                "missing_requirements": list(requirements.missing_required_ids),
            }
        )
        if user_registry is not None:
            routing_ok, routing_errors = StrategicDraft.validate_routing(draft, user_registry)
            if not routing_ok:
                raise ValueError(
                    "Strategic draft routing validation failed: "
                    + "; ".join(routing_errors)
                )
        await self.log(
            f"Plan ready: {artifact_family.value} uses {mode.value} execution with {len(hitl_nodes)} HITL node(s).",
            kind="decision",
            detail={"artifact_family": artifact_family.value, "coverage_score": requirements.coverage_score},
        )
        fan_in_required = bool(task_graph.fan_in_groups)
        return WorkflowPlan(
            workflow_mode=mode,
            analysis_mode=analysis_mode,
            summary=draft.summary,
            direct_answer=False,
            notes=draft.notes,
            artifact_family=artifact_family,
            artifact_spec=artifact_spec,
            requirements_checklist=requirements,
            task_graph=task_graph,
            tasks=tasks,
            hitl_nodes=hitl_nodes,
            content_director_nodes=content_director_nodes,
            available_agents=catalog,
            agent_assignments=assignments,
            topology_reason=draft.topology_reason or topology_reason,
            workflow_template_id=draft.workflow_template_id,
            node_assignments=draft.node_assignments,
            required_tools_per_node=draft.required_tools_per_node,
            fallback_path=draft.fallback_path,
            missing_requirements=draft.missing_requirements,
            fan_in_required=fan_in_required,
        )
