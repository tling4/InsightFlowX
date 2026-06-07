"""
Tests for human-in-the-loop (HITL) mechanism and node recovery/resume.

Covers:
- _pause_router conditional routing logic
- DecisionRequest schema validation
- execute_with_retry: GraphInterrupt propagation, retry behaviour
- ReviewAgent rule-based pause signal generation
- Runtime pause policy and route policy
- POST /{workflow_id}/decide API endpoint (approve/abort/resume/jump)
- Workflow pause_state persistence
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime.retry import execute_with_retry, NodeFatalError
from app.core.competitive_template import CompetitiveAnalysisTemplate
from app.core.runtime.policies import ReviewRoutePolicy
from app.core.runtime.context import AgentContext
from app.schemas.decision import DecisionRequest, DecisionAction
from app.schemas.event import EventType
from app.agents.review_agent import ReviewAgent
from app.schemas.review import ReviewOutput, ReviewCheck
from app.db.models.workflow import Workflow
from langgraph.errors import GraphInterrupt
from types import SimpleNamespace


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
        "primary_issue_type": None if passed else "artifact_inconsistency",
        "issue_types": [] if passed else ["artifact_inconsistency"],
        "affected_entities": [] if passed else ["feature_matrix"],
        "suggested_actions": [] if passed else ["rerun_analysis"],
        "retry_worthiness": "none" if passed else "medium",
    }


def _mock_ctx(node_id: str = "review") -> AgentContext:
    return AgentContext(
        workflow_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        node_id=node_id,
        iteration=0,
        events=SimpleNamespace(
            emit=AsyncMock(),
            progress=AsyncMock(),
            stream_token=AsyncMock(),
        ),
    )


# ---------------------------------------------------------------------------
# TestReviewRouter — pure function tests for conditional edge routing
# ---------------------------------------------------------------------------

class TestReviewRoutePolicy:
    """Tests for reusable runtime route policy."""

    def test_passed_review_routes_to_done(self):
        decision = ReviewRoutePolicy().decide(
            {"data": {"review_result": _make_review_dict(passed=True)}, "control": {}, "runtime": {}},
            CompetitiveAnalysisTemplate.node("review"),
        )
        assert decision.action == "finish"

    def test_none_review_routes_to_done(self):
        decision = ReviewRoutePolicy().decide({"data": {}, "control": {}, "runtime": {}}, CompetitiveAnalysisTemplate.node("review"))
        assert decision.action == "fail"

    def test_passed_review_has_no_target_node_routes_to_done(self):
        decision = ReviewRoutePolicy().decide(
            {"data": {"review_result": _make_review_dict(passed=True, target_node=None)}, "control": {}, "runtime": {}},
            CompetitiveAnalysisTemplate.node("review"),
        )
        assert decision.action == "finish"

    def test_max_revisions_review_routes_to_done(self):
        decision = ReviewRoutePolicy().decide(
            {
                "data": {"review_result": _make_review_dict(passed=False, target_node="analysis")},
                "control": {"revision_count": 3, "max_revisions": 3},
                "runtime": {},
            },
            CompetitiveAnalysisTemplate.node("review"),
        )
        assert decision.action == "fail"

    def test_human_jump_has_priority_over_agent_target(self):
        decision = ReviewRoutePolicy().decide(
            {
                "data": {"review_result": _make_review_dict(passed=False, target_node="analysis")},
                "control": {"human_decision": {"action": "jump", "target_node": "information_collection"}},
                "runtime": {},
            },
            CompetitiveAnalysisTemplate.node("review"),
        )
        assert decision.next_node == "information_collection"

    def test_human_jump_routes_to_target_node(self):
        decision = ReviewRoutePolicy().decide(
            {
                "data": {"review_result": _make_review_dict(passed=False, target_node="analysis")},
                "control": {"human_decision": {"action": "jump", "target_node": "report_writing"}},
                "runtime": {},
            },
            CompetitiveAnalysisTemplate.node("review"),
        )
        assert decision.next_node == "report_writing"

    def test_human_structural_action_routes_to_target_node(self):
        decision = ReviewRoutePolicy().decide(
            {
                "data": {"review_result": _make_review_dict(passed=False, target_node="analysis")},
                "control": {"human_decision": {"action": "drop_competitor", "target_node": "information_collection"}},
                "runtime": {},
            },
            CompetitiveAnalysisTemplate.node("review"),
        )
        assert decision.next_node == "information_collection"

    def test_human_jump_invalid_target_falls_back_to_review_agent_target_on_review_node(self):
        decision = ReviewRoutePolicy().decide(
            {
                "data": {"review_result": _make_review_dict(passed=False, target_node="analysis")},
                "control": {"human_decision": {"action": "jump", "target_node": "bogus_node"}},
                "runtime": {},
            },
            CompetitiveAnalysisTemplate.node("review"),
        )
        assert decision.next_node == "analysis"

    def test_non_jump_action_does_not_reroute_outside_review_node(self):
        spec = CompetitiveAnalysisTemplate.node("analysis")
        assert spec.default_next == "feature_analysis"

    def test_review_node_uses_agent_target_node_once(self):
        decision = ReviewRoutePolicy().decide(
            {
                "data": {"review_result": _make_review_dict(passed=False, target_node="report_writing")},
                "control": {"revision_count": 0, "max_revisions": 3},
                "runtime": {},
            },
            CompetitiveAnalysisTemplate.node("review"),
        )
        assert decision.next_node == "report_writing"

    def test_non_review_node_ignores_agent_target_node(self):
        assert CompetitiveAnalysisTemplate.node("information_collection").default_next == "analysis"

    def test_agent_target_node_invalid_falls_to_done(self):
        decision = ReviewRoutePolicy().decide(
            {"data": {"review_result": _make_review_dict(passed=False, target_node="bogus")}, "control": {}, "runtime": {}},
            CompetitiveAnalysisTemplate.node("review"),
        )
        assert decision.next_node == "analysis"

    def test_missing_target_node_falls_to_done(self):
        review = _make_review_dict(passed=False)
        del review["target_node"]
        decision = ReviewRoutePolicy().decide({"data": {"review_result": review}, "control": {}, "runtime": {}}, CompetitiveAnalysisTemplate.node("review"))
        assert decision.next_node == "analysis"

    def test_human_decision_empty_dict_falls_back_to_review_agent_target_on_review_node(self):
        decision = ReviewRoutePolicy().decide(
            {
                "data": {"review_result": _make_review_dict(passed=False, target_node="information_collection")},
                "control": {"human_decision": {}},
                "runtime": {},
            },
            CompetitiveAnalysisTemplate.node("review"),
        )
        assert decision.next_node == "information_collection"

    def test_no_review_no_human_falls_to_done(self):
        decision = ReviewRoutePolicy().decide({"data": {}, "control": {}, "runtime": {}}, CompetitiveAnalysisTemplate.node("review"))
        assert decision.action == "fail"


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
        dumped = d.model_dump(mode="json", exclude_none=True)
        assert dumped == {"action": "jump", "target_node": "analysis", "feedback": "re-collect"}

    def test_valid_replace_competitor_action(self):
        d = DecisionRequest(
            action=DecisionAction.REPLACE_COMPETITOR,
            target_node="information_collection",
            replacement_competitor="飞书",
        )
        assert d.action == DecisionAction.REPLACE_COMPETITOR
        assert d.replacement_competitor == "飞书"


# ---------------------------------------------------------------------------
# TestExecuteWithRetry — retry / timeout / GraphInterrupt propagation
# ---------------------------------------------------------------------------

class TestExecuteWithRetry:
    """Tests for execute_with_retry: retry behaviour and interrupt propagation."""

    @pytest.mark.asyncio
    async def test_returns_result_on_success(self):
        node_fn = AsyncMock(return_value={"key": "value"})
        event_logger = AsyncMock()
        result = await execute_with_retry(node_fn, {}, "test_node", event_logger)
        assert result == {"key": "value"}
        node_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_graph_interrupt_propagates_immediately_no_retry(self):
        node_fn = AsyncMock(side_effect=GraphInterrupt({"paused": True}))
        event_logger = AsyncMock()
        with pytest.raises(GraphInterrupt):
            await execute_with_retry(node_fn, {}, "test_node", event_logger)
        # No retries — called exactly once
        assert node_fn.await_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_exception_then_succeeds(self):
        call_count = 0

        async def flaky_fn(state):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient error")
            return {"recovered": True}

        event_logger = AsyncMock()
        result = await execute_with_retry(flaky_fn, {}, "test_node", event_logger)
        assert result == {"recovered": True}
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_node_fatal_error_after_max_retries(self):
        node_fn = AsyncMock(side_effect=RuntimeError("persistent failure"))
        event_logger = AsyncMock()
        with pytest.raises(NodeFatalError) as exc_info:
            await execute_with_retry(node_fn, {}, "test_node", event_logger)
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
        assert review.primary_issue_type == "structural_coverage_gap"
        assert "structural_coverage_gap" in review.issue_types
        assert review.retry_worthiness == "low"

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
        assert review.primary_issue_type == "structural_coverage_gap"
        assert "拼多多" in review.affected_entities
        assert "review_competitor_scope" in review.suggested_actions

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
        assert review.target_node == "feature_analysis"
        assert review.primary_issue_type == "artifact_inconsistency"
        assert "rerun_analysis" in review.suggested_actions
        assert review.retry_worthiness == "medium"

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
        assert review.primary_issue_type == "report_render_issue"
        assert "rerender_report" in review.suggested_actions
        assert review.retry_worthiness == "high"

    def test_rule_based_review_classifies_transient_collection_failures(self):
        agent = ReviewAgent()
        state = {
            "config": {
                "target_product": "Notion",
                "product_category": "企业软件 / SaaS",
                "competitors": ["Confluence"],
                "competitor_count": 1,
            },
            "report": {
                "title": "Test Report",
                "executive_summary": "summary here",
                "full_markdown": "x" * 600,
                "sections": [{"title": "s1"}, {"title": "s2"}, {"title": "s3"}, {"title": "s4"}],
                "citations": [{"url": "http://example.com", "title": "ref"}],
            },
            "raw_data": {
                "Notion": [{"url": "http://notion.example"}],
                "Confluence": [],
            },
            "collection_errors": {
                "Confluence": "Request timeout while calling Tavily search API",
                "__source_coverage__": "Missing source coverage for: Confluence",
            },
            "feature_matrix": {"matrix": [{"feature": "f1"}]},
            "pricing_comparison": {"plans": [{"name": "basic"}]},
            "user_sentiment": {"per_product": {"Notion": "positive"}},
            "swot": {"strengths": ["strong brand"]},
        }
        review = agent._rule_based_review(state)
        assert review.passed is False
        assert review.primary_issue_type == "transient_failure"
        assert "transient_failure" in review.issue_types
        assert "structural_coverage_gap" in review.issue_types
        assert "retry_collection" in review.suggested_actions
        assert review.retry_worthiness == "medium"

    def test_rule_based_review_allows_insufficient_evidence_competitor(self):
        agent = ReviewAgent()
        state = {
            "config": {
                "target_product": "淘宝",
                "product_category": "移动应用",
                "competitors": ["京东", "拼多多"],
                "competitor_count": 2,
                "insufficient_evidence_competitors": ["拼多多"],
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
        assert review.passed is True
        assert review.retry_worthiness == "none"

    @pytest.mark.asyncio
    async def test_run_returns_review_result_when_review_fails(self):
        """ReviewAgent now returns business output only; pause is a runtime policy."""
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
        with patch("app.agents.review_agent.llm_is_configured", return_value=False):
            result = await agent.run(state, _mock_ctx())

        assert "review_result" in result
        assert result["review_result"]["passed"] is False

    def test_review_fail_pause_policy_builds_pause_request(self):
        from app.core.competitive_template import CompetitiveAnalysisTemplate
        from app.core.runtime.policies import ReviewFailPausePolicy

        spec = CompetitiveAnalysisTemplate.node("review")
        policy = ReviewFailPausePolicy()
        pause = policy.build_pause(
            {
                "data": {
                    "review_result": _make_review_dict(passed=False, score=45, target_node="analysis"),
                    "revision_count": 0,
                    "max_revisions": 3,
                },
                "control": {"revision_count": 0, "max_revisions": 3},
                "runtime": {"run_id": str(uuid.uuid4()), "thread_id": "thread"},
            },
            spec,
        )

        assert pause is not None
        assert pause.node_id == "review"
        assert pause.suggested_route == "analysis"
        assert len(pause.options) == 3
        assert pause.options[0]["label"] == "重新生成分析结果"
        assert pause.context["primary_issue_type"] == "artifact_inconsistency"

    def test_review_fail_pause_policy_builds_structural_gap_options(self):
        from app.core.competitive_template import CompetitiveAnalysisTemplate
        from app.core.runtime.policies import ReviewFailPausePolicy

        spec = CompetitiveAnalysisTemplate.node("review")
        policy = ReviewFailPausePolicy()
        pause = policy.build_pause(
            {
                "data": {
                    "review_result": {
                        **_make_review_dict(passed=False, score=45, target_node="information_collection"),
                        "primary_issue_type": "structural_coverage_gap",
                        "issue_types": ["structural_coverage_gap"],
                        "affected_entities": ["拼多多"],
                        "suggested_actions": ["review_competitor_scope"],
                        "retry_worthiness": "low",
                    },
                    "revision_count": 0,
                    "max_revisions": 3,
                },
                "control": {"revision_count": 0, "max_revisions": 3},
                "runtime": {"run_id": str(uuid.uuid4()), "thread_id": "thread"},
            },
            spec,
        )

        assert pause is not None
        option_values = [opt["value"] for opt in pause.options]
        assert option_values[:3] == [
            "drop_competitor",
            "keep_with_insufficient_evidence",
            "replace_competitor",
        ]

    def test_review_fail_pause_policy_apply_drop_competitor(self):
        from app.core.runtime.policies import ReviewFailPausePolicy

        policy = ReviewFailPausePolicy()
        applied = policy.apply_decision(
            {
                "data": {
                    "config": {
                        "target_product": "淘宝",
                        "product_category": "移动应用",
                        "competitors": ["京东", "拼多多"],
                        "competitor_groups": {"core": ["京东"], "potential": ["拼多多"]},
                    },
                    "raw_data": {"淘宝": [{"url": "x"}], "京东": [{"url": "y"}], "拼多多": []},
                    "collection_errors": {"拼多多": "timeout", "__source_coverage__": "Missing source coverage for: 拼多多"},
                    "review_result": {"affected_entities": ["拼多多"]},
                },
                "control": {},
            },
            None,
            {"action": "drop_competitor"},
        )

        config = applied["data"]["config"]
        assert config["competitors"] == ["京东"]
        assert "拼多多" not in (config.get("competitor_groups", {}).get("potential") or [])
        assert "拼多多" not in applied["data"]["raw_data"]
        assert "__source_coverage__" not in applied["data"]["collection_errors"]
        assert applied["decision"]["target_node"] == "information_collection"

    def test_review_fail_pause_policy_apply_drop_competitor_falls_back_when_explicit_invalid(self):
        from app.core.runtime.policies import ReviewFailPausePolicy

        policy = ReviewFailPausePolicy()
        applied = policy.apply_decision(
            {
                "data": {
                    "config": {
                        "target_product": "淘宝",
                        "product_category": "移动应用",
                        "competitors": ["京东", "拼多多"],
                    },
                    "review_result": {"affected_entities": ["拼多多"]},
                },
                "control": {},
            },
            None,
            {"action": "drop_competitor", "competitor": "输入框残留文本"},
        )

        assert applied["data"]["config"]["competitors"] == ["京东"]
        assert applied["decision"]["target_node"] == "information_collection"
        assert applied["decision"]["feedback"] == "移除竞品：拼多多"
        assert applied["control"]["human_decision"]["feedback"] == "移除竞品：拼多多"

    def test_review_fail_pause_policy_apply_keep_insufficient_evidence(self):
        from app.core.runtime.policies import ReviewFailPausePolicy

        policy = ReviewFailPausePolicy()
        applied = policy.apply_decision(
            {
                "data": {
                    "config": {
                        "target_product": "淘宝",
                        "product_category": "移动应用",
                        "competitors": ["京东", "拼多多"],
                    },
                    "review_result": {"affected_entities": ["拼多多"]},
                },
                "control": {},
            },
            None,
            {"action": "keep_with_insufficient_evidence"},
        )

        config = applied["data"]["config"]
        assert "拼多多" in config["insufficient_evidence_competitors"]
        assert applied["decision"]["target_node"] == "report_writing"
        assert "证据不足" in config["extra_requirements"]

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
        with patch("app.agents.review_agent.llm_is_configured", return_value=False):
            result = await agent.run(state, _mock_ctx())

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
        with patch("app.agents.review_agent.llm_is_configured", return_value=False):
            result = await agent.run(state, _mock_ctx())

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
        ctx = _mock_ctx()
        with patch("app.agents.review_agent.llm_is_configured", return_value=False):
            result = await agent.run(state, ctx)

        emitted_event_types = [
            call.args[0].value if hasattr(call.args[0], "value") else str(call.args[0])
            for call in ctx.events.emit.await_args_list
        ]
        assert EventType.REVIEW_FAILED_MAX_REVISIONS.value in emitted_event_types


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
