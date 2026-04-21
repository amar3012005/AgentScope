from types import SimpleNamespace
import asyncio

import pytest

from agentscope_blaiq.contracts.artifact import ArtifactSection, VisualArtifact
from agentscope_blaiq.contracts.agent_catalog import AgentCapability, AgentSkill, AgentStatus, LiveAgentProfile
from agentscope_blaiq.contracts.evidence import EvidenceFinding, EvidencePack
from agentscope_blaiq.contracts.workflow import AgentRunPayload, AgentType, ResumeWorkflowRequest, SubmitWorkflowRequest, WorkflowMode, WorkflowPlan, WorkflowStatus
import agentscope_blaiq.workflows.engine as workflow_engine_module
from agentscope_blaiq.persistence.repositories import WorkflowRepository
from agentscope_blaiq.workflows.engine import WorkflowEngine


class FakeWorkflowRepository:
    def __init__(self, session, state_store=None):
        self.events = session.setdefault("events", [])
        self.status = session.setdefault("status", {})
        self.records = session.setdefault("records", {})
        self.state_store = state_store

    async def create_workflow(self, request, run_id=None, workflow_plan_json=None):
        self.status[request.thread_id] = {"status": "queued"}
        self.records[request.thread_id] = {
            "thread_id": request.thread_id,
            "run_id": run_id,
            "session_id": request.session_id,
            "tenant_id": request.tenant_id,
            "workflow_mode": request.workflow_mode.value if hasattr(request.workflow_mode, "value") else request.workflow_mode,
            "analysis_mode": request.analysis_mode.value if hasattr(request.analysis_mode, "value") else request.analysis_mode,
            "user_query": request.user_query,
            "artifact_type": request.artifact_type,
            "source_scope": request.source_scope,
            "workflow_plan_json": workflow_plan_json,
        }
        return self.status[request.thread_id]

    async def get_workflow_record(self, thread_id):
        record = self.records.get(thread_id)
        return SimpleNamespace(**record) if record is not None else None

    async def append_event(self, event):
        self.events.append(event)

    async def update_workflow_snapshot(
        self,
        thread_id,
        *,
        run_id=None,
        status=None,
        current_node=None,
        current_phase=None,
        current_agent=None,
        latest_event=None,
        error_message=None,
        workflow_mode=None,
        workflow_plan_json=None,
        final_artifact_json=None,
        **kwargs,
    ):
        snapshot = self.status.setdefault(thread_id, {})
        if status is not None:
            snapshot["status"] = status.value if hasattr(status, "value") else status
        if latest_event is not None:
            snapshot["latest_event"] = latest_event
        if current_node is not None:
            snapshot["current_node"] = current_node
        if current_phase is not None:
            snapshot["current_phase"] = current_phase
        if current_agent is not None:
            snapshot["current_agent"] = current_agent
        if error_message is not None:
            snapshot["error_message"] = error_message
        if workflow_mode is not None:
            snapshot["workflow_mode"] = workflow_mode.value if hasattr(workflow_mode, "value") else workflow_mode
        if workflow_plan_json is not None:
            snapshot["workflow_plan_json"] = workflow_plan_json
        if final_artifact_json is not None:
            snapshot["final_artifact_json"] = final_artifact_json
        for key, value in kwargs.items():
            if value is not None:
                snapshot[key] = value

    async def build_submit_request(self, thread_id):
        record = self.records.get(thread_id)
        if record is None:
            return None
        return SubmitWorkflowRequest(
            user_query=record["user_query"],
            workflow_mode=WorkflowMode(record["workflow_mode"]),
            analysis_mode=record["analysis_mode"],
            tenant_id=record["tenant_id"],
            session_id=record["session_id"],
            thread_id=record["thread_id"],
            artifact_type=record["artifact_type"],
            source_scope=record["source_scope"],
        )

    async def get_status(self, thread_id):
        snapshot = self.status.get(thread_id)
        if snapshot is None:
            return None
        record = self.records.get(thread_id, {})
        return SimpleNamespace(
            thread_id=thread_id,
            session_id=record.get("session_id"),
            run_id=record.get("run_id"),
            status=WorkflowStatus(snapshot.get("status", "queued")),
            current_node=snapshot.get("current_node", "planning"),
            current_agent=snapshot.get("current_agent", "strategist"),
            latest_event=snapshot.get("latest_event"),
            final_artifact=snapshot.get("final_artifact_json"),
            error_message=snapshot.get("error_message"),
            artifact_family=snapshot.get("artifact_family"),
            blocked_question=snapshot.get("blocked_question"),
            expected_answer_schema=snapshot.get("expected_answer_schema"),
            requirements_checklist=snapshot.get("requirements_checklist"),
            pending_node=snapshot.get("pending_node", snapshot.get("current_node")),
            resume_count=snapshot.get("resume_count", 0),
            last_resume_reason=snapshot.get("last_resume_reason"),
            updated_at=snapshot.get("updated_at"),
        )

    async def set_final_artifact(self, thread_id, artifact):
        self.status[thread_id] = {"status": "complete", "artifact": artifact}


class FakeArtifactRepository:
    def __init__(self, session):
        self.session = session

    async def save(self, thread_id, tenant_id, artifact, html_path, css_path):
        self.session.setdefault("artifacts", {})[thread_id] = artifact


class FakeEvidenceRepository:
    def __init__(self, session):
        self.session = session

    async def save(self, thread_id, tenant_id, evidence_id, evidence):
        self.session.setdefault("evidence", {})[thread_id] = evidence

    async def list_for_thread(self, thread_id):
        evidence = self.session.setdefault("evidence", {}).get(thread_id)
        if evidence is None:
            return []
        return [SimpleNamespace(evidence_json=evidence.model_dump_json())]


class FakeAgentRunRepository:
    def __init__(self, session):
        self.session = session

    async def create_run(self, *, thread_id, tenant_id, agent_name, agent_type, branch_id=None, input_json=None):
        run_id = f"{agent_name}-{len(self.session.setdefault('agent_runs', [])) + 1}"
        record = SimpleNamespace(
            run_id=run_id,
            thread_id=thread_id,
            tenant_id=tenant_id,
            agent_name=agent_name,
            agent_type=agent_type,
            branch_id=branch_id,
            input_json=input_json or {},
            status="running",
        )
        self.session.setdefault("agent_runs", []).append(record)
        return record

    async def mark_complete(self, run_id, output_json=None):
        self.session.setdefault("agent_run_status", {})[run_id] = {"status": "complete", "output": output_json or {}}

    async def mark_failed(self, run_id, error_message):
        self.session.setdefault("agent_run_status", {})[run_id] = {"status": "error", "error_message": error_message}


@pytest.fixture(autouse=True)
def fake_repositories(monkeypatch):
    monkeypatch.setattr(workflow_engine_module, "WorkflowRepository", FakeWorkflowRepository)
    monkeypatch.setattr(workflow_engine_module, "ArtifactRepository", FakeArtifactRepository)
    monkeypatch.setattr(workflow_engine_module, "EvidenceRepository", FakeEvidenceRepository)
    monkeypatch.setattr(workflow_engine_module, "AgentRunRepository", FakeAgentRunRepository)


@pytest.fixture
def session():
    return {}


class FakeStrategist:
    def __init__(self):
        self.agent_catalog = []

    async def build_plan(self, request, agent_catalog=None):
        self.agent_catalog = agent_catalog or []
        return WorkflowPlan(
            workflow_mode=request.workflow_mode,
            summary="test plan",
            tasks=[AgentRunPayload(agent_type=AgentType.research, purpose="test")],
            available_agents=agent_catalog or [],
        )


class FakeResearch:
    async def gather(self, session, tenant_id, query, scope, quick_recall=False):
        return EvidencePack(summary=f"{scope} evidence", confidence=0.8)

    async def answer_question(self, query, evidence, response_depth=None):
        return f"Direct answer for: {query}"


class RichDirectAnswerResearch(FakeResearch):
    async def gather(self, session, tenant_id, query, scope, quick_recall=False):
        return EvidencePack(
            summary=f"{scope} evidence",
            confidence=0.9,
            memory_findings=[
                EvidenceFinding(
                    finding_id="memory:1",
                    title="Product catalog",
                    summary="The company sells three products.",
                    source_ids=["source-1"],
                    confidence=0.9,
                )
            ],
        )


class FakeVangogh:
    async def generate(self, user_query, evidence, content_brief=None, on_section_ready=None, brand_dna=None):
        return VisualArtifact(
            artifact_id="artifact-1",
            title="Artifact",
            sections=[
                ArtifactSection(
                    section_id="hero",
                    section_index=0,
                    title="Hero",
                    summary="Hero section",
                    html_fragment="<section>Hero</section>",
                )
            ],
            evidence_refs=["source-1"],
            html="<html></html>",
            css="body{}",
        )


class FakeGovernance:
    async def review(self, artifact, evidence):
        class _Report:
            def model_dump(self_inner):
                return {"approved": True, "issues": [], "readiness_score": 1.0}

        return _Report()


class FakeContentDirector:
    async def plan_content(self, *, user_query, evidence_summary, artifact_spec, requirements, hitl_answers=None, evidence_pack=None):
        return SimpleNamespace(
            model_dump=lambda: {
                "title": user_query,
                "family": getattr(getattr(artifact_spec, "family", None), "value", "custom"),
                "template_name": "default",
                "narrative": evidence_summary,
                "section_plan": [],
                "distribution_notes": [],
                "handoff_notes": [],
            }
        )


class FakeHITL:
    async def generate_prompt(
        self,
        *,
        user_query,
        artifact_family,
        requirements,
        missing_requirement_ids,
        evidence_summary=None,
        target_audience=None,
        delivery_channel=None,
        brand_context=None,
    ):
        questions = [
            {
                "requirement_id": requirement.requirement_id,
                "question": requirement.text,
                "why_it_matters": "",
                "answer_hint": requirement.text,
            }
            for requirement in requirements.items
            if requirement.requirement_id in missing_requirement_ids
        ]
        return SimpleNamespace(
            headline="Clarification needed",
            intro="Please provide the missing details.",
            questions=questions,
            blocked_question=" ".join(question["question"] for question in questions),
            expected_answer_schema={question["requirement_id"]: question["question"] for question in questions},
            family=artifact_family,
        )


class FakeRegistry:
    def __init__(self):
        self.strategist = FakeStrategist()
        self.hitl = FakeHITL()
        self.research = FakeResearch()
        self.content_director = FakeContentDirector()
        self.vangogh = FakeVangogh()
        self.governance = FakeGovernance()
        self.hivemind = SimpleNamespace(
            enterprise_chat_enabled=False,
            rpc_url=None,
            recall=self._recall,
            traverse_graph=self._traverse_graph,
        )

    async def _recall(self, query, limit=5, mode="quick"):
        return {"memories": []}

    async def _traverse_graph(self, memory_id, depth=3):
        return {"nodes": [], "edges": []}

    def mark_agent_busy(self, name, stage=None):
        return None

    def mark_agent_ready(self, name, stage=None):
        return None

    def list_live_profiles(self):
        return [
            LiveAgentProfile(
                name="hitl",
                role="human clarification",
                status=AgentStatus.ready,
                capabilities=[AgentCapability(name="clarification_dialogue", description="Frame missing requirements as natural language questions.")],
                skills=[AgentSkill(name="question_framing")],
                tools=["clarify_requirements"],
            ),
            LiveAgentProfile(
                name="research",
                role="evidence gathering",
                status=AgentStatus.ready,
                capabilities=[AgentCapability(name="web_research", description="Fetch web sources.")],
                skills=[AgentSkill(name="source_citation")],
                tools=["fetch_url_summary"],
            ),
            LiveAgentProfile(
                name="vangogh",
                role="visual artifact generation",
                status=AgentStatus.ready,
                capabilities=[AgentCapability(name="artifact_layout", description="Compose layouts.")],
                skills=[AgentSkill(name="editorial_layout")],
                tools=["artifact_contract"],
            ),
            LiveAgentProfile(
                name="content_director",
                role="content planning",
                status=AgentStatus.ready,
                capabilities=[AgentCapability(name="content_distribution", description="Plan content distribution.")],
                skills=[AgentSkill(name="render_brief_generation")],
                tools=["content_distribution"],
            ),
            LiveAgentProfile(
                name="governance",
                role="validation",
                status=AgentStatus.ready,
                capabilities=[AgentCapability(name="artifact_validation", description="Validate artifacts.")],
                skills=[AgentSkill(name="quality_gate")],
                tools=["validate_visual_artifact"],
            ),
        ]


@pytest.mark.asyncio
async def test_sequential_workflow_emits_terminal_event(session):
    engine = WorkflowEngine(FakeRegistry())
    request = SubmitWorkflowRequest(user_query="Create a strategy visual", workflow_mode=WorkflowMode.sequential)
    events = [event async for event in engine.run(session, request)]
    assert events[0].type == "workflow_submitted"
    assert events[-1].type == "workflow_complete"
    assert any(event.type == "artifact_ready" for event in events)


@pytest.mark.asyncio
async def test_parallel_workflow_emits_fanin(session):
    engine = WorkflowEngine(FakeRegistry())
    request = SubmitWorkflowRequest(user_query="Create a research-backed visual", workflow_mode=WorkflowMode.parallel)
    events = [event async for event in engine.run(session, request)]
    event_types = [event.type for event in events]
    assert "parallel_branch_started" in event_types
    assert "fanin_completed" in event_types
    assert event_types[-1] == "workflow_complete"


class SlowStrategist(FakeStrategist):
    async def build_plan(self, request, agent_catalog=None):
        await asyncio.sleep(0.2)
        return await super().build_plan(request, agent_catalog=agent_catalog)


class SlowRegistry(FakeRegistry):
    def __init__(self):
        super().__init__()
        self.strategist = SlowStrategist()


class DirectAnswerStrategist(FakeStrategist):
    async def build_plan(self, request, agent_catalog=None):
        return WorkflowPlan(
            workflow_mode=WorkflowMode.sequential,
            summary="Direct knowledge question routed to research-only answer path.",
            direct_answer=True,
            tasks=[AgentRunPayload(agent_type=AgentType.research, purpose="Research and answer directly")],
            available_agents=agent_catalog or [],
        )


class DirectAnswerRegistry(FakeRegistry):
    def __init__(self):
        super().__init__()
        self.strategist = DirectAnswerStrategist()


class RichDirectAnswerRegistry(DirectAnswerRegistry):
    def __init__(self):
        super().__init__()
        self.research = RichDirectAnswerResearch()


class DepthAwareResearch(RichDirectAnswerResearch):
    def __init__(self):
        self.response_depth_calls: list[str | None] = []

    async def answer_question(self, query, evidence, response_depth=None):
        self.response_depth_calls.append(response_depth)
        return f"Depth={response_depth or 'unset'} for: {query}"


class DepthAwareRegistry(DirectAnswerRegistry):
    def __init__(self):
        super().__init__()
        self.research = DepthAwareResearch()


class FakeEnterpriseHivemind:
    def __init__(self):
        self.enterprise_chat_enabled = True
        self.rpc_url = "https://core.hivemind.davinciai.eu/servers/user-456/rpc"
        self.calls: list[dict[str, object]] = []

    async def save_enterprise_chat_turn(self, **kwargs):
        self.calls.append(dict(kwargs))
        turn_number = kwargs.get("turn_number") or 1
        turn = kwargs.get("turn")
        status = "pending" if turn == "user" else "complete"
        return SimpleNamespace(
            sid=kwargs["sid"],
            turn_number=turn_number,
            turn_memory_id=f"tm-{turn}-{turn_number}",
            status=status,
            raw={"sid": kwargs["sid"], "turn_number": turn_number, "status": status},
        )

    async def recall(self, query, limit=5, mode="quick"):
        return {"memories": []}

    async def traverse_graph(self, memory_id, depth=3):
        return {"nodes": [], "edges": []}


class EnterpriseRegistry(DirectAnswerRegistry):
    def __init__(self):
        super().__init__()
        self.hivemind = FakeEnterpriseHivemind()


@pytest.mark.asyncio
async def test_workflow_streams_immediate_submission_before_plan_resolves(session):
    engine = WorkflowEngine(SlowRegistry())
    request = SubmitWorkflowRequest(user_query="Create a streamed plan", workflow_mode=WorkflowMode.hybrid)
    stream = engine.run(session, request)

    first_event = await asyncio.wait_for(stream.__anext__(), timeout=0.1)
    second_event = await asyncio.wait_for(stream.__anext__(), timeout=0.1)

    assert first_event.type == "workflow_submitted"
    assert second_event.type == "planning_started"

    remaining_events = [event async for event in stream]
    assert any(event.type == "planning_complete" for event in remaining_events)


@pytest.mark.asyncio
async def test_direct_knowledge_query_returns_final_answer_without_artifact_or_hitl(session):
    engine = WorkflowEngine(DirectAnswerRegistry())
    request = SubmitWorkflowRequest(user_query="what do u know about me", workflow_mode=WorkflowMode.hybrid, source_scope="web")

    events = [event async for event in engine.run(session, request)]
    event_types = [event.type for event in events]

    assert event_types[0] == "workflow_submitted"
    assert "agent_completed" in event_types
    assert "workflow_blocked" not in event_types
    assert "artifact_ready" not in event_types
    assert event_types[-1] == "workflow_complete"
    assert events[-1].data["final_answer"] == "Direct answer for: what do u know about me"
    assert events[-1].data["final_artifact"] is None


@pytest.mark.asyncio
async def test_typoed_direct_knowledge_query_returns_final_answer_without_artifact_or_hitl(session):
    engine = WorkflowEngine(DirectAnswerRegistry())
    request = SubmitWorkflowRequest(user_query="what di u know about me", workflow_mode=WorkflowMode.hybrid, source_scope="web")

    events = [event async for event in engine.run(session, request)]
    event_types = [event.type for event in events]

    assert event_types[0] == "workflow_submitted"
    assert "agent_completed" in event_types
    assert "workflow_blocked" not in event_types
    assert "artifact_ready" not in event_types
    assert event_types[-1] == "workflow_complete"
    assert events[-1].data["final_answer"] == "Direct answer for: what di u know about me"
    assert events[-1].data["final_artifact"] is None


@pytest.mark.asyncio
async def test_count_query_routes_to_direct_answer(session):
    engine = WorkflowEngine(DirectAnswerRegistry())
    request = SubmitWorkflowRequest(user_query="how many products do we sell", workflow_mode=WorkflowMode.hybrid, source_scope="web")

    events = [event async for event in engine.run(session, request)]
    event_types = [event.type for event in events]

    assert event_types[0] == "workflow_submitted"
    assert "artifact_ready" not in event_types
    assert "workflow_blocked" not in event_types
    assert event_types[-1] == "workflow_complete"
    assert events[-1].data["final_answer"] == "Direct answer for: how many products do we sell"
    assert events[-1].data["final_artifact"] is None


@pytest.mark.asyncio
async def test_direct_answer_with_sources_blocks_for_depth_choice(session):
    engine = WorkflowEngine(RichDirectAnswerRegistry())
    request = SubmitWorkflowRequest(user_query="how many products do we sell", workflow_mode=WorkflowMode.hybrid, source_scope="web")

    events = [event async for event in engine.run(session, request)]
    event_types = [event.type for event in events]

    assert event_types[0] == "workflow_submitted"
    assert "workflow_blocked" in event_types
    assert "artifact_ready" not in event_types
    assert event_types[-1] == "workflow_blocked"
    blocked_event = next(event for event in events if event.type == "workflow_blocked")
    assert blocked_event.data["pending_node"] == "hitl_depth"
    assert blocked_event.data["questions"][0]["requirement_id"] == "field:response_depth"


@pytest.mark.asyncio
async def test_resume_passes_selected_depth_into_final_synthesis(session):
    engine = WorkflowEngine(DepthAwareRegistry())
    thread_id = "thread-depth-001"
    submit_request = SubmitWorkflowRequest(
        user_query="how many products do we sell",
        workflow_mode=WorkflowMode.hybrid,
        source_scope="web",
        thread_id=thread_id,
        session_id="session-depth-001",
    )

    first_events = [event async for event in engine.run(session, submit_request)]
    assert any(event.type == "workflow_blocked" for event in first_events)

    resume_request = ResumeWorkflowRequest(
        thread_id=thread_id,
        tenant_id="default",
        resume_reason="User chose response depth",
        answers={
            "field:response_depth": "Full technical breakdown — 3-5 paragraphs with deeper product and system detail",
        },
    )

    resumed_events = [event async for event in engine.resume(session, resume_request)]
    assert resumed_events[-1].type == "workflow_complete"
    assert resumed_events[-1].data["final_answer"] == (
        "Depth=Full technical breakdown — 3-5 paragraphs with deeper product and system detail for: how many products do we sell"
    )
    assert engine.registry.research.response_depth_calls == [
        "Full technical breakdown — 3-5 paragraphs with deeper product and system detail"
    ]


@pytest.mark.asyncio
async def test_enterprise_chat_saves_new_chat_then_old_for_final_response(session, monkeypatch):
    monkeypatch.setattr(workflow_engine_module.settings, "hivemind_enterprise_org_id", "org-123")
    monkeypatch.setattr(workflow_engine_module.settings, "hivemind_enterprise_user_id", "user-456")

    engine = WorkflowEngine(EnterpriseRegistry())
    request = SubmitWorkflowRequest(
        user_query="what do u know about me",
        workflow_mode=WorkflowMode.hybrid,
        source_scope="web",
        session_id="chat-session-1",
        thread_id="thread-1",
    )

    events = [event async for event in engine.run(session, request)]

    assert events[-1].type == "workflow_complete"
    assert request.memory_chain_id == "tm-agent-1"

    calls = engine.registry.hivemind.calls
    assert len(calls) == 2

    user_call, agent_call = calls
    assert user_call["sid"] == "chat-session-1"
    assert user_call["turn"] == "user"
    assert user_call["content"] == "what do u know about me"
    assert user_call["is_new_chat"] is True
    assert user_call["idempotency_key"] == "chat-session-1-user-1"

    assert agent_call["sid"] == "chat-session-1"
    assert agent_call["turn"] == "agent"
    assert agent_call["content"] == events[-1].data["final_answer_display"]
    assert agent_call["is_new_chat"] is False
    assert agent_call["turn_number"] == 1
    assert agent_call["idempotency_key"] == "chat-session-1-agent-1"


@pytest.mark.asyncio
async def test_prepare_resume_preserves_post_research_hitl_cursor():
    repository = WorkflowRepository(session=SimpleNamespace())
    calls: list[dict[str, object]] = []

    async def get_record(thread_id):
        return SimpleNamespace(
            status="blocked",
            thread_id=thread_id,
            session_id="session-1",
            tenant_id="tenant-1",
            workflow_mode="hybrid",
            user_query="Create a pitch deck",
            workflow_state_json=None,
        )

    async def get_status(thread_id):
        return SimpleNamespace(
            pending_node="hitl_evidence",
            resume_cursor="hitl_evidence",
            last_completed_node="research",
        )

    async def build_submit_request_from_record(record, tenant_id=None):
        return SubmitWorkflowRequest(user_query=record.user_query, workflow_mode=WorkflowMode.hybrid)

    async def update_workflow_snapshot(thread_id, **kwargs):
        calls.append({"thread_id": thread_id, **kwargs})

    repository.get_record = get_record  # type: ignore[method-assign]
    repository.get_status = get_status  # type: ignore[method-assign]
    repository.build_submit_request_from_record = build_submit_request_from_record  # type: ignore[method-assign]
    repository.update_workflow_snapshot = update_workflow_snapshot  # type: ignore[method-assign]

    submit_request = await repository.prepare_resume(SimpleNamespace(thread_id="thread-1", tenant_id="tenant-1"))

    assert submit_request.user_query == "Create a pitch deck"
    assert calls
    assert calls[0]["pending_node"] == "hitl_evidence"
    assert calls[0]["resume_cursor"] == "hitl_evidence"
    assert calls[0]["last_completed_node"] == "research"
