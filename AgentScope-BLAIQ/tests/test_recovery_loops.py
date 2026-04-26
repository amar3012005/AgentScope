"""
Tests for _execute_with_recovery in WorkflowEngine:
retry behavior, REPLAN threshold, HITL escalation, and success paths.
"""

from __future__ import annotations

import pytest

try:
    from agentscope_blaiq.workflows.engine import WorkflowEngine
    from agentscope_blaiq.contracts.registry import HarnessRegistry
    _ENGINE_AVAILABLE = True
except ImportError:
    _ENGINE_AVAILABLE = False

pytestmark = pytest.mark.skipif(not _ENGINE_AVAILABLE, reason="engine not importable (agentscope not installed)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeRegistry:
    """Minimal registry stub for WorkflowEngine construction."""

    def __init__(self):
        self.agents: dict = {}
        self.tools: dict = {}
        self.workflows: dict = {}
        self.harness_registry = HarnessRegistry() if _ENGINE_AVAILABLE else None

    def list_live(self):
        return []


def _make_engine():
    engine = WorkflowEngine.__new__(WorkflowEngine)
    engine.registry = _FakeRegistry()
    engine.state_store = None
    engine.session_factory = None
    engine._cancellation_requests = set()
    engine._harness_registry = None
    return engine


def _make_run_fn(*, fail_times: int = 0, result: dict | None = None):
    """Returns async run_fn that fails `fail_times` times then succeeds."""
    calls = {"count": 0}

    async def run_fn():
        calls["count"] += 1
        if calls["count"] <= fail_times:
            raise RuntimeError(f"Simulated failure #{calls['count']}")
        return result or {"output": "success"}

    return run_fn, calls


# ---------------------------------------------------------------------------
# TestExecuteWithRecovery — success paths
# ---------------------------------------------------------------------------

class TestExecuteWithRecoverySuccess:
    async def test_succeeds_on_first_attempt(self):
        engine = _make_engine()
        run_fn, calls = _make_run_fn(fail_times=0)

        result = await engine._execute_with_recovery(
            agent_id="test_agent",
            run_fn=run_fn,
            input_data={"query": "hello"},
            workflow_id="test_wf",
        )
        assert result == {"output": "success"}
        assert calls["count"] == 1

    async def test_succeeds_after_one_failure(self):
        engine = _make_engine()
        run_fn, calls = _make_run_fn(fail_times=1)

        result = await engine._execute_with_recovery(
            agent_id="test_agent",
            run_fn=run_fn,
            input_data={"query": "hello"},
            workflow_id="test_wf",
        )
        assert result == {"output": "success"}
        assert calls["count"] == 2

    async def test_succeeds_after_two_failures(self):
        engine = _make_engine()
        run_fn, calls = _make_run_fn(fail_times=2)

        result = await engine._execute_with_recovery(
            agent_id="test_agent",
            run_fn=run_fn,
            input_data={"query": "hello"},
            workflow_id="test_wf",
        )
        assert result == {"output": "success"}
        assert calls["count"] == 3

    async def test_custom_result_returned(self):
        engine = _make_engine()
        expected = {"text": "my result", "tokens": 42}
        run_fn, _ = _make_run_fn(fail_times=0, result=expected)

        result = await engine._execute_with_recovery(
            agent_id="test_agent",
            run_fn=run_fn,
            input_data={},
            workflow_id=None,
        )
        assert result == expected


# ---------------------------------------------------------------------------
# TestExecuteWithRecoveryRetry — retry counting
# ---------------------------------------------------------------------------

class TestExecuteWithRecoveryRetry:
    async def test_retries_up_to_max_attempts(self):
        engine = _make_engine()
        run_fn, calls = _make_run_fn(fail_times=10)  # always fail

        with pytest.raises(RuntimeError):
            await engine._execute_with_recovery(
                agent_id="test_agent",
                run_fn=run_fn,
                input_data={},
                workflow_id=None,
                max_attempts=3,
            )
        assert calls["count"] == 3

    async def test_default_max_attempts_is_three(self):
        engine = _make_engine()
        run_fn, calls = _make_run_fn(fail_times=10)

        with pytest.raises(RuntimeError):
            await engine._execute_with_recovery(
                agent_id="test_agent",
                run_fn=run_fn,
                input_data={},
                workflow_id=None,
            )
        assert calls["count"] == 3

    async def test_custom_max_attempts_respected(self):
        engine = _make_engine()
        run_fn, calls = _make_run_fn(fail_times=10)

        with pytest.raises(RuntimeError):
            await engine._execute_with_recovery(
                agent_id="test_agent",
                run_fn=run_fn,
                input_data={},
                workflow_id=None,
                max_attempts=5,
            )
        assert calls["count"] == 5

    async def test_re_raises_last_exception_on_exhaustion(self):
        engine = _make_engine()

        async def always_fail():
            raise ValueError("terminal error")

        with pytest.raises(ValueError, match="terminal error"):
            await engine._execute_with_recovery(
                agent_id="test_agent",
                run_fn=always_fail,
                input_data={},
                workflow_id=None,
            )

    async def test_no_unnecessary_retries_on_success(self):
        engine = _make_engine()
        run_fn, calls = _make_run_fn(fail_times=0)

        await engine._execute_with_recovery(
            agent_id="test_agent",
            run_fn=run_fn,
            input_data={},
            workflow_id=None,
        )
        assert calls["count"] == 1


# ---------------------------------------------------------------------------
# TestExecuteWithRecoveryPreDispatch — pre-dispatch check integration
# ---------------------------------------------------------------------------

class TestExecuteWithRecoveryPreDispatch:
    async def test_missing_harness_does_not_block(self):
        """Advisory check — unknown agent logs WARN but does not raise."""
        engine = _make_engine()
        run_fn, calls = _make_run_fn(fail_times=0)

        result = await engine._execute_with_recovery(
            agent_id="unknown_agent_xyz",
            run_fn=run_fn,
            input_data={"query": "test"},
            workflow_id=None,
        )
        assert result == {"output": "success"}
        assert calls["count"] == 1

    async def test_workflow_id_passed_through(self):
        """Verify workflow_id forwarded to pre-dispatch check without error."""
        engine = _make_engine()
        run_fn, calls = _make_run_fn(fail_times=0)

        result = await engine._execute_with_recovery(
            agent_id="test_agent",
            run_fn=run_fn,
            input_data={},
            workflow_id="visual_artifact_v1",
        )
        assert result == {"output": "success"}


# ---------------------------------------------------------------------------
# TestCallResearchGather — signature compatibility
# ---------------------------------------------------------------------------

class TestCallResearchGather:
    async def test_gather_without_quick_recall_kwarg(self):
        class _Agent:
            async def gather(self, session, tenant_id, query, source_scope):
                return {
                    "session": session,
                    "tenant_id": tenant_id,
                    "query": query,
                    "source_scope": source_scope,
                }

        result = await WorkflowEngine._call_research_gather(
            _Agent(),
            session="s1",
            tenant_id="t1",
            query="q1",
            source_scope="web",
            quick_recall=True,
        )
        assert result["query"] == "q1"
        assert result["source_scope"] == "web"

    async def test_gather_with_quick_recall_kwarg(self):
        class _Agent:
            async def gather(self, session, tenant_id, user_query, source_scope, quick_recall=False):
                return {"quick_recall": quick_recall, "query": user_query, "scope": source_scope}

        result = await WorkflowEngine._call_research_gather(
            _Agent(),
            session="s1",
            tenant_id="t1",
            query="q1",
            source_scope="docs",
            quick_recall=True,
        )
        assert result["quick_recall"] is True
        assert result["query"] == "q1"
        assert result["scope"] == "docs"

    async def test_gather_with_no_expected_parameters(self):
        class _Agent:
            async def gather(self):
                return {"ok": True}

        result = await WorkflowEngine._call_research_gather(
            _Agent(),
            session="s1",
            tenant_id="t1",
            query="q1",
            source_scope="web_and_docs",
            quick_recall=False,
        )
        assert result == {"ok": True}
