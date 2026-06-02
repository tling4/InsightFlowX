"""
Tests for human-in-the-loop (HITL) mechanism and node recovery/resume.

Covers:
- _pause_router conditional routing logic
- DecisionRequest schema validation
- execute_with_retry: GraphInterrupt propagation, retry behaviour
- ReviewAgent rule-based pause signal generation
- _execute_node pause detection and interrupt()
- POST /{workflow_id}/decide API endpoint (approve/abort/resume/jump)
- Workflow pause_state persistence
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.orchestrator import make_pause_router
from app.core.node_executor import execute_with_retry, NodeFatalError
from app.schemas.decision import DecisionRequest, DecisionAction
from app.schemas.event import EventType
from app.agents.review_agent import ReviewAgent
from app.schemas.review import ReviewOutput, ReviewCheck
from app.db.models.workflow import Workflow
from langgraph.errors import GraphInterrupt


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _get_auth_token(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json={
        "username": "hitl_test",
        "email": "hitl@example.com",
        "password": "12345678",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "hitl@example.com",
        "password": "12345678",
    })
    return resp.json()["access_token"]


def _make_review_dict(passed: bool, score: float = 75.0, target_node: str = "analysis") -> dict:
    return {
        "passed": passed,
        "score": score,
        "checks": [{"dimension": "completeness", "passed": passed, "detail": "ok"}],
        "feedback": "ok" if passed else "needs work",
        "target_node": target_node if not passed else None,
        "specific_issues": [] if passed else ["issue 1"],
    }


# ---------------------------------------------------------------------------
# TestReviewRouter — pure function tests for conditional edge routing
# ---------------------------------------------------------------------------

class TestPauseRouter:
    """Tests for make_pause_router(current_node, default_next)(state)."""

    def test_passed_review_routes_to_done(self):
        state = {"review_result": _make_review_dict(passed=True)}
        assert make_pause_router("review", "done")(state) == "done"

    def test_none_review_routes_to_done(self):
        assert make_pause_router("review", "done")({}) == "done"
        assert make_pause_router("review", "done")({"review_result": None}) == "done"

    def test_passed_review_has_no_target_node_routes_to_done(self):
        """Passed review sets target_node=None, router sees no valid target → done."""
        state = {"review_result": _make_review_dict(passed=True, target_node=None)}
        assert make_pause_router("review", "done")(state) == "done"

    def test_max_revisions_review_routes_to_done(self):
        """When max_revisions is reached, stale target_node no longer reroutes."""
        state = {
            "review_result": _make_review_dict(passed=False, target_node="analysis"),
            "revision_count": 3,
            "max_revisions": 3,
        }
        assert make_pause_router("review", "done")(state) == "done"

    def test_human_jump_has_priority_over_agent_target(self):
        """Human jump target takes priority over agent's suggested target_node."""
        state = {
            "review_result": _make_review_dict(passed=False, target_node="analysis"),
            "human_decision": {"action": "jump", "target_node": "information_collection"},
        }
        route = make_pause_router("review", "done")(state)
        assert route == "information_collection"

    def test_human_jump_routes_to_target_node(self):
        state = {
            "review_result": _make_review_dict(passed=False, target_node="analysis"),
            "human_decision": {"action": "jump", "target_node": "report_writing"},
        }
        route = make_pause_router("review", "done")(state)
        assert route == "report_writing"

    def test_human_jump_invalid_target_falls_back_to_review_agent_target_on_review_node(self):
        state = {
            "review_result": _make_review_dict(passed=False, target_node="analysis"),
            "human_decision": {"action": "jump", "target_node": "bogus_node"},
        }
        route = make_pause_router("review", "done")(state)
        assert route == "analysis"

    def test_non_jump_action_does_not_reroute_outside_review_node(self):
        """Non-review nodes must ignore stale review_result.target_node."""
        state = {
            "review_result": _make_review_dict(passed=False, target_node="information_collection"),
            "human_decision": {"action": "approve"},
        }
        assert make_pause_router("information_collection", "analysis")(state) == "analysis"

    def test_review_node_uses_agent_target_node_once(self):
        state = {
            "review_result": _make_review_dict(passed=False, target_node="report_writing"),
            "revision_count": 0,
            "max_revisions": 3,
        }
        route = make_pause_router("review", "done")(state)
        assert route == "report_writing"

    def test_non_review_node_ignores_agent_target_node(self):
        state = {
            "review_result": _make_review_dict(passed=False, target_node="information_collection"),
        }
        assert make_pause_router("information_collection", "analysis")(state) == "analysis"

    def test_agent_target_node_invalid_falls_to_done(self):
        """Invalid agent target_node → done (no reroute)."""
        state = {
            "review_result": _make_review_dict(passed=False, target_node="bogus"),
        }
        assert make_pause_router("review", "done")(state) == "done"

    def test_missing_target_node_falls_to_done(self):
        """No target_node anywhere → done (no reroute)."""
        review = _make_review_dict(passed=False)
        del review["target_node"]
        state = {"review_result": review}
        assert make_pause_router("review", "done")(state) == "done"

    def test_human_decision_empty_dict_falls_back_to_review_agent_target_on_review_node(self):
        state = {
            "review_result": _make_review_dict(passed=False, target_node="information_collection"),
            "human_decision": {},
        }
        route = make_pause_router("review", "done")(state)
        assert route == "information_collection"

    def test_no_review_no_human_falls_to_done(self):
        """Neither review_result nor human_decision → done."""
        assert make_pause_router("review", "done")({}) == "done"


# ---------------------------------------------------------------------------
# TestDecisionRequest — schema validation
# ---------------------------------------------------------------------------

class TestDecisionRequest:
    def test_valid_approve_action(self):
        d = DecisionRequest(action=DecisionAction.APPROVE)
        assert d.action == DecisionAction.APPROVE
        assert d.target_node is None
        assert d.feedback == ""

    def test_valid_abort_action(self):
        d = DecisionRequest(action=DecisionAction.ABORT)
        assert d.action == DecisionAction.ABORT

    def test_valid_jump_action(self):
        d = DecisionRequest(action=DecisionAction.JUMP, target_node="information_collection")
        assert d.action == DecisionAction.JUMP

    def test_jump_without_target_node(self):
        d = DecisionRequest(action=DecisionAction.JUMP)
        assert d.target_node is None
        assert d.feedback == ""

    def test_model_dump_json(self):
        d = DecisionRequest(action=DecisionAction.JUMP, target_node="analysis", feedback="re-collect")
        dumped = d.model_dump(mode="json")
        assert dumped == {"action": "jump", "target_node": "analysis", "feedback": "re-collect"}


# ---------------------------------------------------------------------------
# TestExecuteWithRetry — retry / timeout / GraphInterrupt propagation
# ---------------------------------------------------------------------------

class TestExecuteWithRetry:
    """Tests for execute_with_retry: retry behaviour and interrupt propagation."""

    @pytest.mark.asyncio
    async def test_returns_result_on_success(self):
        node_fn = AsyncMock(return_value={"key": "value"})
        event_logger = AsyncMock()
        result = await execute_with_retry(node_fn, {}, "test_node", event_logger, uuid.uuid4())
        assert result == {"key": "value"}
        node_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_graph_interrupt_propagates_immediately_no_retry(self):
        node_fn = AsyncMock(side_effect=GraphInterrupt({"paused": True}))
        event_logger = AsyncMock()
        with pytest.raises(GraphInterrupt):
            await execute_with_retry(node_fn, {}, "test_node", event_logger, uuid.uuid4())
        # No retries — called exactly once
        assert node_fn.await_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_exception_then_succeeds(self):
        call_count = 0

        async def flaky_fn(state, event_logger, workflow_id):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient error")
            return {"recovered": True}

        event_logger = AsyncMock()
        result = await execute_with_retry(flaky_fn, {}, "test_node", event_logger, uuid.uuid4())
        assert result == {"recovered": True}
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_node_fatal_error_after_max_retries(self):
        node_fn = AsyncMock(side_effect=RuntimeError("persistent failure"))
        event_logger = AsyncMock()
        with pytest.raises(NodeFatalError) as exc_info:
            await execute_with_retry(node_fn, {}, "test_node", event_logger, uuid.uuid4())
        assert exc_info.value.node == "test_node"
        assert exc_info.value.attempts == 3
        assert isinstance(exc_info.value.last_error, RuntimeError)
        # 3 attempts = 3 calls (no retry after the 3rd failure)
        assert node_fn.await_count == 3


# ---------------------------------------------------------------------------
# TestReviewAgentRuleBased — rule-based review pause signal generation
# ---------------------------------------------------------------------------

class TestReviewAgentRuleBased:
    """Tests for ReviewAgent._rule_based_review and run() pause signal logic."""

    def test_rule_based_review_passed_no_pause(self):
        agent = ReviewAgent()
        state = {
            "report": {
                "title": "Test Report",
                "executive_summary": "summary here",
                "full_markdown": "x" * 600,
                "sections": [{"title": "s1"}, {"title": "s2"}, {"title": "s3"}, {"title": "s4"}],
                "citations": [{"url": "http://example.com", "title": "ref"}],
            },
            "raw_data": {"product_a": [{"url": "http://x.com"}]},
            "feature_matrix": {"matrix": [{"feature": "f1"}]},
            "pricing_comparison": {"plans": [{"name": "basic"}]},
            "user_sentiment": {"per_product": {"a": "positive"}},
            "swot": {"strengths": ["strong brand"]},
        }
        review = agent._rule_based_review(state)
        assert review.passed is True
        assert review.score >= 70

    def test_rule_based_review_failed_due_to_no_sources(self):
        agent = ReviewAgent()
        state = {
            "report": {
                "title": "Test",
                "executive_summary": "summary",
                "full_markdown": "x" * 600,
                "sections": [{"title": "s1"}, {"title": "s2"}, {"title": "s3"}, {"title": "s4"}],
                "citations": [],
            },
            "raw_data": {},
            "feature_matrix": {"matrix": [{"feature": "f1"}]},
            "pricing_comparison": {"plans": [{"name": "basic"}]},
            "user_sentiment": {"per_product": {"a": "positive"}},
            "swot": {"strengths": ["strong brand"]},
        }
        review = agent._rule_based_review(state)
        assert review.passed is False
        assert review.target_node == "information_collection"

    def test_rule_based_review_failed_due_to_missing_competitor_source(self):
        agent = ReviewAgent()
        state = {
            "config": {
                "target_product": "淘宝",
                "product_category": "移动应用",
                "competitors": ["京东", "拼多多"],
                "competitor_count": 2,
            },
            "report": {
                "title": "Test Report",
                "executive_summary": "summary here",
                "full_markdown": "x" * 600,
                "sections": [{"title": "s1"}, {"title": "s2"}, {"title": "s3"}, {"title": "s4"}],
                "citations": [{"url": "http://example.com", "title": "ref"}],
            },
            "raw_data": {
                "淘宝": [{"url": "http://taobao.example"}],
                "京东": [{"url": "http://jd.example"}],
                "拼多多": [],
            },
            "collection_errors": {"__source_coverage__": "Missing source coverage for: 拼多多"},
            "feature_matrix": {"matrix": [{"feature": "f1"}]},
            "pricing_comparison": {"plans": [{"name": "basic"}]},
            "user_sentiment": {"per_product": {"淘宝": "positive"}},
            "swot": {"strengths": ["strong brand"]},
        }
        review = agent._rule_based_review(state)
        assert review.passed is False
        assert review.target_node == "information_collection"
        assert "Missing source coverage for: 拼多多" in review.feedback
        assert "以下产品缺少来源：拼多多" in review.feedback

    def test_rule_based_review_failed_due_to_analysis_gaps(self):
        agent = ReviewAgent()
        state = {
            "report": {
                "title": "Test",
                "executive_summary": "summary",
                "full_markdown": "short",
                "sections": [{"title": "s1"}],
                "citations": [{"url": "http://example.com"}],
            },
            "raw_data": {"product_a": [{"url": "http://x.com"}]},
            "feature_matrix": {},
            "pricing_comparison": {},
            "user_sentiment": {},
            "swot": {},
        }
        review = agent._rule_based_review(state)
        assert review.passed is False
        assert review.target_node == "analysis"

    def test_rule_based_review_failed_due_to_report_structure(self):
        agent = ReviewAgent()
        state = {
            "report": {
                "title": "",
                "executive_summary": "",
                "full_markdown": "short",
                "sections": [{"title": "s1"}],
                "citations": [{"url": "http://example.com"}],
            },
            "raw_data": {"product_a": [{"url": "http://x.com"}]},
            "feature_matrix": {"matrix": [{"feature": "f1"}]},
            "pricing_comparison": {"plans": [{"name": "basic"}]},
            "user_sentiment": {"per_product": {"a": "positive"}},
            "swot": {"strengths": ["strong brand"]},
        }
        review = agent._rule_based_review(state)
        assert review.passed is False
        assert review.target_node == "report_writing"

    @pytest.mark.asyncio
    async def test_run_returns_pause_signal_when_review_fails(self):
        """When LLM is not configured, rule-based review runs.  Verify the pause
        signal shape returned when the review doesn't pass."""
        agent = ReviewAgent()
        state = {
            "config": {"target_product": "test"},
            "report": {
                "title": "Test",
                "executive_summary": "summary",
                "full_markdown": "x" * 600,
                "sections": [{"title": "s1"}, {"title": "s2"}, {"title": "s3"}, {"title": "s4"}],
                "citations": [],
            },
            "raw_data": {},
            "feature_matrix": {"matrix": [{"feature": "f1"}]},
            "pricing_comparison": {"plans": [{"name": "basic"}]},
            "user_sentiment": {"per_product": {"a": "positive"}},
            "swot": {"strengths": ["strong brand"]},
            "revision_count": 0,
            "max_revisions": 3,
        }
        event_logger = AsyncMock()
        with patch("app.agents.review_agent.llm_is_configured", return_value=False):
            result = await agent.run(state, event_logger, uuid.uuid4())

        assert result.get("__pause__") is True
        assert "pause_reason" in result
        assert "pause_options" in result
        assert "pause_context" in result
        assert "review_result" in result
        assert len(result["pause_options"]) == 3

    @pytest.mark.asyncio
    async def test_run_no_pause_when_max_revisions_reached(self):
        agent = ReviewAgent()
        state = {
            "config": {"target_product": "test"},
            "report": {
                "title": "Test",
                "executive_summary": "summary",
                "full_markdown": "x" * 600,
                "sections": [{"title": "s1"}, {"title": "s2"}, {"title": "s3"}, {"title": "s4"}],
                "citations": [],
            },
            "raw_data": {},
            "feature_matrix": {"matrix": [{"feature": "f1"}]},
            "pricing_comparison": {"plans": [{"name": "basic"}]},
            "user_sentiment": {"per_product": {"a": "positive"}},
            "swot": {"strengths": ["strong brand"]},
            "revision_count": 3,
            "max_revisions": 3,
        }
        event_logger = AsyncMock()
        with patch("app.agents.review_agent.llm_is_configured", return_value=False):
            result = await agent.run(state, event_logger, uuid.uuid4())

        assert "__pause__" not in result
        assert "review_result" in result

    @pytest.mark.asyncio
    async def test_run_no_pause_when_review_passes(self):
        agent = ReviewAgent()
        state = {
            "config": {"target_product": "test"},
            "report": {
                "title": "Test Report",
                "executive_summary": "summary",
                "full_markdown": "x" * 600,
                "sections": [{"title": "s1"}, {"title": "s2"}, {"title": "s3"}, {"title": "s4"}],
                "citations": [{"url": "http://example.com"}],
            },
            "raw_data": {"product_a": [{"url": "http://x.com"}]},
            "feature_matrix": {"matrix": [{"feature": "f1"}]},
            "pricing_comparison": {"plans": [{"name": "basic"}]},
            "user_sentiment": {"per_product": {"a": "positive"}},
            "swot": {"strengths": ["strong brand"]},
            "revision_count": 0,
            "max_revisions": 3,
        }
        event_logger = AsyncMock()
        with patch("app.agents.review_agent.llm_is_configured", return_value=False):
            result = await agent.run(state, event_logger, uuid.uuid4())

        assert "__pause__" not in result
        assert result["review_result"]["passed"] is True

    @pytest.mark.asyncio
    async def test_max_revisions_emits_review_failed_event(self):
        """When max_revisions reached, REVIEW_FAILED_MAX_REVISIONS event is emitted."""
        agent = ReviewAgent()
        state = {
            "config": {"target_product": "test"},
            "report": {
                "title": "",
                "executive_summary": "",
                "full_markdown": "short",
                "sections": [{"title": "s1"}],
                "citations": [],
            },
            "raw_data": {},
            "feature_matrix": {"matrix": [{"feature": "f1"}]},
            "pricing_comparison": {"plans": [{"name": "basic"}]},
            "user_sentiment": {"per_product": {"a": "positive"}},
            "swot": {"strengths": ["strong brand"]},
            "revision_count": 3,
            "max_revisions": 3,
        }
        event_logger = AsyncMock()
        with patch("app.agents.review_agent.llm_is_configured", return_value=False):
            result = await agent.run(state, event_logger, uuid.uuid4())

        assert "__pause__" not in result
        # log_and_broadcast internally calls event_logger.log(); check for the
        # REVIEW_FAILED_MAX_REVISIONS event type in those calls
        event_types_called = []
        for c in event_logger.log.call_args_list:
            et = c.kwargs.get("event_type") or (c.args[0] if c.args else None)
            if et is not None:
                event_types_called.append(et.value if hasattr(et, 'value') else str(et))
        assert EventType.REVIEW_FAILED_MAX_REVISIONS.value in event_types_called


# ---------------------------------------------------------------------------
# TestExecuteNodePauseDetection — _execute_node interrupt/resume paths
# ---------------------------------------------------------------------------

class TestExecuteNodePauseDetection:
    """Tests for _execute_node's __pause__ detection and interrupt() call."""

    @pytest.mark.asyncio
    async def test_pause_signal_calls_interrupt(self):
        from app.core.graph_nodes import _execute_node

        db = AsyncMock(spec=AsyncSession)
        event_logger = AsyncMock()
        event_logger.with_node.return_value = event_logger
        wf_id = uuid.uuid4()

        async def agent_run(state, el, wid):
            return {"__pause__": True, "pause_reason": "test pause", "data": "value"}

        with patch("app.core.graph_nodes.interrupt") as mock_interrupt:
            await _execute_node(db, wf_id, 1, "review", {}, event_logger, agent_run)

        mock_interrupt.assert_called_once()
        pause_data = mock_interrupt.call_args[0][0]
        assert pause_data["paused_by_node"] == "review"
        assert pause_data["pause_reason"] == "test pause"
        assert "dag_state" in pause_data
        # dag_state should include business data (not __ keys)
        assert pause_data["dag_state"]["data"] == "value"
        assert "__pause__" not in pause_data["dag_state"]

    @pytest.mark.asyncio
    async def test_resume_path_with_human_decision_skips_interrupt(self):
        from app.core.graph_nodes import _execute_node

        db = AsyncMock(spec=AsyncSession)
        event_logger = AsyncMock()
        event_logger.with_node.return_value = event_logger
        wf_id = uuid.uuid4()

        state = {"human_decision": {"action": "jump", "target_node": "analysis"}, "revision_count": 0}

        async def agent_run(state, el, wid):
            return {"__pause__": True, "pause_reason": "should not pause", "data": "value"}

        with patch("app.core.graph_nodes.interrupt") as mock_interrupt:
            result = await _execute_node(db, wf_id, 1, "review", state, event_logger, agent_run)

        # interrupt() must NOT be called when human_decision is already in state
        mock_interrupt.assert_not_called()
        # Result should merge business data + human_decision + incremented revision_count
        assert result["data"] == "value"
        assert result["human_decision"] == {"action": "jump", "target_node": "analysis"}
        assert result["revision_count"] == 1

    @pytest.mark.asyncio
    async def test_no_pause_without_signal(self):
        from app.core.graph_nodes import _execute_node

        db = AsyncMock(spec=AsyncSession)
        event_logger = AsyncMock()
        event_logger.with_node.return_value = event_logger
        wf_id = uuid.uuid4()

        async def agent_run(state, el, wid):
            return {"data": "normal result"}

        with patch("app.core.graph_nodes.interrupt") as mock_interrupt:
            result = await _execute_node(db, wf_id, 1, "analysis", {}, event_logger, agent_run)

        mock_interrupt.assert_not_called()
        assert result == {"data": "normal result"}


# ---------------------------------------------------------------------------
# TestCachedReviewResultSkip — make_review_node skips agent on resume
# ---------------------------------------------------------------------------

class TestCachedReviewResultSkip:
    """Tests for make_review_node cached_review_result short-circuit."""

    @pytest.mark.asyncio
    async def test_cached_review_skips_agent_call(self):
        """When state has human_decision + cached_review_result, ReviewAgent.run is skipped."""
        from app.core.graph_nodes import make_review_node

        db = AsyncMock(spec=AsyncSession)
        event_logger = AsyncMock()
        event_logger.with_node.return_value = event_logger
        wf_id = uuid.uuid4()

        review_node = make_review_node(db, wf_id, event_logger, 1)
        cached = _make_review_dict(passed=False, score=45, target_node="analysis")
        state = {
            "human_decision": {"action": "jump", "target_node": "analysis"},
            "cached_review_result": cached,
            "revision_count": 0,
        }
        with patch("app.core.graph_nodes._review_agent.run") as mock_run:
            result = await review_node(state)

        mock_run.assert_not_called()
        assert result["revision_count"] == 1
        assert result["score"] == 45
        assert result["human_decision"] is None
        assert result["cached_review_result"] is None
        assert result["review_reroute_target"] == "analysis"
        assert result["review_result_consumed"] is True

    @pytest.mark.asyncio
    async def test_no_cached_result_calls_agent_normally(self):
        """Without cached_review_result, agent is called normally."""
        from app.core.graph_nodes import make_review_node

        db = AsyncMock(spec=AsyncSession)
        event_logger = AsyncMock()
        event_logger.with_node.return_value = event_logger
        wf_id = uuid.uuid4()

        review_node = make_review_node(db, wf_id, event_logger, 1)
        state = {
            "human_decision": {"action": "jump", "target_node": "analysis"},
            "revision_count": 0,
        }
        with patch("app.core.graph_nodes._review_agent.run") as mock_run:
            mock_run.return_value = {"review_result": _make_review_dict(passed=False), "current_phase": "reviewing"}
            await review_node(state)

        mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# TestDecideEndpoint — POST /{workflow_id}/decide API integration
# ---------------------------------------------------------------------------

class TestDecideEndpoint:
    """Integration tests for the human decision endpoint."""

    @pytest.mark.asyncio
    async def test_approve_paused_workflow(self, client: AsyncClient, db_session: AsyncSession):
        token = await _get_auth_token(client)

        # Create workflow
        resp = await client.post(
            "/api/v1/workflows",
            json={"title": "decide-approve-test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        wf_id = resp.json()["workflow_id"]

        # Set workflow to paused via direct DB
        wf = await db_session.get(Workflow, uuid.UUID(wf_id))
        wf.status = "paused"
        wf.pause_state = {
            "paused_by_node": "review",
            "pause_reason": "test pause",
            "pause_options": [{"value": "retry", "label": "重试"}],
        }
        await db_session.commit()

        # POST /decide with approve
        resp = await client.post(
            f"/api/v1/workflows/{wf_id}/decide",
            json={"action": "approve"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["action"] == "approve"

        # Verify DB state
        await db_session.refresh(wf)
        assert wf.status == "completed"
        assert wf.pause_state is None

    @pytest.mark.asyncio
    async def test_abort_paused_workflow(self, client: AsyncClient, db_session: AsyncSession):
        token = await _get_auth_token(client)

        resp = await client.post(
            "/api/v1/workflows",
            json={"title": "decide-abort-test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        wf_id = resp.json()["workflow_id"]

        wf = await db_session.get(Workflow, uuid.UUID(wf_id))
        wf.status = "paused"
        wf.pause_state = {"paused_by_node": "review", "pause_reason": "test"}
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/workflows/{wf_id}/decide",
            json={"action": "abort"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["action"] == "abort"

        await db_session.refresh(wf)
        assert wf.status == "cancelled"
        assert wf.pause_state is None

    @pytest.mark.asyncio
    async def test_jump_triggers_background_task(self, client: AsyncClient, db_session: AsyncSession):
        token = await _get_auth_token(client)

        resp = await client.post(
            "/api/v1/workflows",
            json={"title": "decide-jump-bg-test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        wf_id = resp.json()["workflow_id"]

        wf = await db_session.get(Workflow, uuid.UUID(wf_id))
        wf.status = "paused"
        wf.pause_state = {"paused_by_node": "review", "pause_reason": "test"}
        await db_session.commit()

        with patch("app.api.v1.workflow.resume_workflow") as mock_resume:
            resp = await client.post(
                f"/api/v1/workflows/{wf_id}/decide",
                json={"action": "jump", "target_node": "analysis", "feedback": "try again"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["action"] == "jump"
        assert mock_resume.call_count >= 1

    @pytest.mark.asyncio
    async def test_decide_on_non_paused_workflow_fails(self, client: AsyncClient, db_session: AsyncSession):
        token = await _get_auth_token(client)

        resp = await client.post(
            "/api/v1/workflows",
            json={"title": "decide-bad-state"},
            headers={"Authorization": f"Bearer {token}"},
        )
        wf_id = resp.json()["workflow_id"]
        # workflow is in "configuring" state — not "paused"

        resp = await client.post(
            f"/api/v1/workflows/{wf_id}/decide",
            json={"action": "approve"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400  # InvalidStateTransitionError

    @pytest.mark.asyncio
    async def test_approve_emits_workflow_complete_sse(self, client: AsyncClient, db_session: AsyncSession):
        token = await _get_auth_token(client)

        resp = await client.post(
            "/api/v1/workflows",
            json={"title": "approve-sse-test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        wf_id = resp.json()["workflow_id"]

        wf = await db_session.get(Workflow, uuid.UUID(wf_id))
        wf.status = "paused"
        wf.pause_state = {"paused_by_node": "review", "pause_reason": "test"}
        await db_session.commit()

        with patch("app.api.v1.workflow.sse_manager.broadcast") as mock_broadcast:
            resp = await client.post(
                f"/api/v1/workflows/{wf_id}/decide",
                json={"action": "approve"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        broadcast_calls = [c[0][1]["event_type"] for c in mock_broadcast.call_args_list]
        assert "workflow_complete" in broadcast_calls

    @pytest.mark.asyncio
    async def test_abort_emits_workflow_failed_sse(self, client: AsyncClient, db_session: AsyncSession):
        token = await _get_auth_token(client)

        resp = await client.post(
            "/api/v1/workflows",
            json={"title": "abort-sse-test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        wf_id = resp.json()["workflow_id"]

        wf = await db_session.get(Workflow, uuid.UUID(wf_id))
        wf.status = "paused"
        wf.pause_state = {"paused_by_node": "review", "pause_reason": "test"}
        await db_session.commit()

        with patch("app.api.v1.workflow.sse_manager.broadcast") as mock_broadcast:
            resp = await client.post(
                f"/api/v1/workflows/{wf_id}/decide",
                json={"action": "abort"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        broadcast_calls = [c[0][1]["event_type"] for c in mock_broadcast.call_args_list]
        assert "workflow_failed" in broadcast_calls
        # Verify error code
        error_calls = [c[0][1] for c in mock_broadcast.call_args_list if c[0][1].get("error_code") == "USER_ABORTED"]
        assert len(error_calls) == 1

    @pytest.mark.asyncio
    async def test_decide_on_nonexistent_workflow_fails(self, client: AsyncClient):
        token = await _get_auth_token(client)
        fake_id = "00000000-0000-0000-0000-000000000000"

        resp = await client.post(
            f"/api/v1/workflows/{fake_id}/decide",
            json={"action": "approve"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404  # WorkflowNotFoundError


# ---------------------------------------------------------------------------
# TestWorkflowPauseState — persistence of pause metadata on Workflow row
# ---------------------------------------------------------------------------

class TestWorkflowPauseState:
    """Tests for pause_state column on the Workflow model."""

    @pytest.mark.asyncio
    async def test_pause_state_persisted_in_db(self, client: AsyncClient, db_session: AsyncSession):
        token = await _get_auth_token(client)

        resp = await client.post(
            "/api/v1/workflows",
            json={"title": "pause-state-test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        wf_id = resp.json()["workflow_id"]

        wf = await db_session.get(Workflow, uuid.UUID(wf_id))
        pause_state = {
            "paused_by_node": "review",
            "pause_reason": "needs human input",
            "pause_options": [
                {"value": "retry", "label": "重试", "target_node": "analysis"},
                {"value": "approve", "label": "强制通过"},
                {"value": "abort", "label": "放弃"},
            ],
            "pause_context": {"score": 55.0},
            "paused_at": "2026-01-01T00:00:00+00:00",
        }
        wf.status = "paused"
        wf.pause_state = pause_state
        await db_session.commit()

        # Verify round-trip
        await db_session.refresh(wf)
        assert wf.status == "paused"
        assert wf.pause_state["paused_by_node"] == "review"
        assert wf.pause_state["pause_reason"] == "needs human input"
        assert len(wf.pause_state["pause_options"]) == 3
        assert wf.pause_state["pause_context"]["score"] == 55.0

    @pytest.mark.asyncio
    async def test_pause_state_cleared_after_approve(self, client: AsyncClient, db_session: AsyncSession):
        token = await _get_auth_token(client)

        resp = await client.post(
            "/api/v1/workflows",
            json={"title": "pause-clear-test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        wf_id = resp.json()["workflow_id"]

        wf = await db_session.get(Workflow, uuid.UUID(wf_id))
        wf.status = "paused"
        wf.pause_state = {"paused_by_node": "review", "pause_reason": "test"}
        await db_session.commit()

        # Approve via API
        await client.post(
            f"/api/v1/workflows/{wf_id}/decide",
            json={"action": "approve"},
            headers={"Authorization": f"Bearer {token}"},
        )

        await db_session.refresh(wf)
        assert wf.status == "completed"
        assert wf.pause_state is None

    @pytest.mark.asyncio
    async def test_pause_state_cleared_after_abort(self, client: AsyncClient, db_session: AsyncSession):
        token = await _get_auth_token(client)

        resp = await client.post(
            "/api/v1/workflows",
            json={"title": "pause-abort-clear"},
            headers={"Authorization": f"Bearer {token}"},
        )
        wf_id = resp.json()["workflow_id"]

        wf = await db_session.get(Workflow, uuid.UUID(wf_id))
        wf.status = "paused"
        wf.pause_state = {"paused_by_node": "review", "pause_reason": "test"}
        await db_session.commit()

        await client.post(
            f"/api/v1/workflows/{wf_id}/decide",
            json={"action": "abort"},
            headers={"Authorization": f"Bearer {token}"},
        )

        await db_session.refresh(wf)
        assert wf.status == "cancelled"
        assert wf.pause_state is None

    @pytest.mark.asyncio
    async def test_workflow_detail_returns_pause_state(self, client: AsyncClient, db_session: AsyncSession):
        token = await _get_auth_token(client)

        resp = await client.post(
            "/api/v1/workflows",
            json={"title": "detail-pause-test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        wf_id = resp.json()["workflow_id"]

        wf = await db_session.get(Workflow, uuid.UUID(wf_id))
        wf.status = "paused"
        wf.pause_state = {
            "paused_by_node": "review",
            "pause_reason": "awaiting human decision",
            "pause_options": [{"value": "retry", "label": "重试", "target_node": "analysis"}],
        }
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/workflows/{wf_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "paused"
        assert data["pause_state"]["paused_by_node"] == "review"
        assert data["pause_state"]["pause_reason"] == "awaiting human decision"
        assert len(data["pause_state"]["pause_options"]) == 1


# ---------------------------------------------------------------------------
# TestRetryEndpoint — POST /{workflow_id}/retry/{node_name}
# ---------------------------------------------------------------------------

class TestRetryEndpoint:
    """Tests for the retry endpoint that recovers from failed/paused states."""

    @pytest.mark.asyncio
    async def test_retry_from_failed_state(self, client: AsyncClient, db_session: AsyncSession):
        token = await _get_auth_token(client)

        resp = await client.post(
            "/api/v1/workflows",
            json={"title": "retry-failed-test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        wf_id = resp.json()["workflow_id"]

        wf = await db_session.get(Workflow, uuid.UUID(wf_id))
        wf.status = "failed"
        wf.error_message = "something went wrong"
        wf.execution_attempt = 1
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/workflows/{wf_id}/retry/analysis",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["execution_attempt"] == 2
        assert data["retry_node"] == "analysis"

        await db_session.refresh(wf)
        assert wf.status == "running"
        assert wf.error_message is None

    @pytest.mark.asyncio
    async def test_retry_from_paused_state(self, client: AsyncClient, db_session: AsyncSession):
        token = await _get_auth_token(client)

        resp = await client.post(
            "/api/v1/workflows",
            json={"title": "retry-paused-test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        wf_id = resp.json()["workflow_id"]

        wf = await db_session.get(Workflow, uuid.UUID(wf_id))
        wf.status = "paused"
        wf.pause_state = {"paused_by_node": "review", "pause_reason": "test"}
        wf.execution_attempt = 1
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/workflows/{wf_id}/retry/review",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["execution_attempt"] == 2

    @pytest.mark.asyncio
    async def test_retry_from_invalid_state_fails(self, client: AsyncClient, db_session: AsyncSession):
        token = await _get_auth_token(client)

        resp = await client.post(
            "/api/v1/workflows",
            json={"title": "retry-bad-state"},
            headers={"Authorization": f"Bearer {token}"},
        )
        wf_id = resp.json()["workflow_id"]
        # workflow is in "configuring" state

        resp = await client.post(
            f"/api/v1/workflows/{wf_id}/retry/analysis",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400  # InvalidStateTransitionError
