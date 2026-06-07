import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.analysis_agent import AnalysisAgent
from app.agents.base_agent import BaseAgent
from app.agents.collection_agent import CollectionAgent
from app.agents.report_agent import ReportAgent
from app.agents.review_agent import ReviewAgent
from app.core.competitive_template import CompetitiveAnalysisTemplate
from app.core.runtime.context import AgentContext, EventSink
from app.core.runtime.policies import ReviewFailPausePolicy
from app.schemas.event import EventType


class DummyAgent(BaseAgent):
    node_name = "analysis"


def _mock_ctx(node_id: str = "analysis") -> AgentContext:
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


@pytest.mark.asyncio
async def test_emit_progress_logs_and_broadcasts():
    agent = DummyAgent()
    event_logger = AsyncMock()
    event_logger.log = AsyncMock(return_value=SimpleNamespace(
        node_name="analysis",
        seq=7,
        created_at="2026-01-01T00:00:00Z",
    ))

    ctx = AgentContext(
        workflow_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        node_id="analysis",
        iteration=0,
        events=EventSink(event_logger, uuid.uuid4(), "analysis"),
    )
    with patch("app.core.runtime.context.sse_manager.broadcast", new=AsyncMock()) as broadcast:
        await agent.emit_progress(ctx, stage="prepare_context", message="正在整理来源上下文。", level="info")

    event_logger.log.assert_awaited_once_with(
        event_type=EventType.NODE_PROGRESS,
        payload={
            "stage": "prepare_context",
            "message": "正在整理来源上下文。",
            "level": "info",
        },
    )
    broadcast.assert_awaited_once()
    payload = broadcast.await_args.args[1]
    assert payload["event_type"] == EventType.NODE_PROGRESS.value
    assert payload["payload"]["stage"] == "prepare_context"
    assert payload["payload"]["message"] == "正在整理来源上下文。"


@pytest.mark.asyncio
async def test_collection_agent_emits_progress_messages():
    agent = CollectionAgent()
    agent.emit_progress = AsyncMock()
    ctx = _mock_ctx("information_collection")

    state = {
        "config": {
            "target_product": "Notion",
            "product_category": "SaaS / 协作工具",
            "competitors": ["语雀"],
            "competitor_count": 1,
            "focus_dimensions": ["功能", "定价"],
        },
    }

    with patch("app.agents.collection_agent.tavily_is_configured", return_value=False):
        result = await agent.run(state, ctx)

    assert result["collection_errors"]["Notion"]
    assert agent.emit_progress.await_count >= 2


@pytest.mark.asyncio
async def test_analysis_agent_emits_progress_messages():
    agent = AnalysisAgent()
    agent.emit_progress = AsyncMock()
    ctx = _mock_ctx("analysis")

    state = {
        "config": {
            "target_product": "Notion",
            "competitors": ["语雀"],
            "focus_dimensions": ["功能", "定价"],
        },
        "raw_data": {
            "Notion": [{"title": "Notion 定价", "url": "https://example.com/notion"}],
            "语雀": [{"title": "语雀 功能", "url": "https://example.com/yuque"}],
        },
    }

    with patch("app.agents.analysis_agent.llm_is_configured", return_value=False):
        result = await agent.run(state, ctx)

    assert result["swot"]["strengths"]
    assert result["feature_matrix"] is None
    assert agent.emit_progress.await_count >= 2


@pytest.mark.asyncio
async def test_feature_analysis_subnode_emits_progress_and_outputs_artifact():
    agent = AnalysisAgent()
    agent.emit_progress = AsyncMock()
    ctx = _mock_ctx("feature_analysis")

    state = {
        "config": {
            "target_product": "Notion",
            "competitors": ["语雀"],
            "focus_dimensions": ["功能", "定价"],
        },
        "raw_data": {
            "Notion": [{"title": "Notion 定价", "url": "https://example.com/notion"}],
            "语雀": [{"title": "语雀 功能", "url": "https://example.com/yuque"}],
        },
    }

    with patch("app.agents.analysis_agent.llm_is_configured", return_value=False):
        result = await agent.run(state, ctx)

    assert result["feature_matrix"]["matrix"]
    assert agent.emit_progress.await_count >= 2


@pytest.mark.asyncio
async def test_feature_analysis_subnode_retries_instead_of_saving_invalid_fallback():
    agent = AnalysisAgent()
    agent.emit_progress = AsyncMock()
    agent._invoke_subnode_llm = AsyncMock(side_effect=ValueError("invalid structured output"))
    ctx = _mock_ctx("feature_analysis")

    state = {
        "config": {
            "target_product": "支付宝",
            "competitors": ["微信支付"],
            "focus_dimensions": ["手续费策略"],
        },
        "raw_data": {
            "支付宝": [{"title": "支付宝手续费", "url": "https://example.com/alipay"}],
            "微信支付": [{"title": "微信支付手续费", "url": "https://example.com/wechat"}],
        },
    }

    with patch("app.agents.analysis_agent.llm_is_configured", return_value=True):
        with pytest.raises(ValueError, match="invalid structured output"):
            await agent.run(state, ctx)

    assert not any(
        call.kwargs.get("stage") == "subnode_complete"
        for call in agent.emit_progress.await_args_list
    )


@pytest.mark.asyncio
async def test_report_agent_emits_progress_messages():
    agent = ReportAgent()
    agent.emit_progress = AsyncMock()
    ctx = _mock_ctx("report_writing")

    state = {
        "config": {"target_product": "Notion"},
        "raw_data": {
            "Notion": [{"url": "https://example.com/notion", "title": "Notion"}],
            "语雀": [{"url": "https://example.com/yuque", "title": "语雀"}],
        },
        "collection_errors": {},
        "feature_matrix": {"matrix": [{"feature_name": "功能", "products": {"Notion": "有", "语雀": "有"}}]},
        "pricing_comparison": {"plans": [], "summary": "summary"},
        "user_sentiment": {"per_product": {}, "common_praises": [], "common_complaints": []},
        "swot": {"strengths": ["强"], "weaknesses": ["弱"], "opportunities": ["机"], "threats": ["威"]},
    }

    with patch("app.agents.report_agent.llm_is_configured", return_value=False):
        result = await agent.run(state, ctx)

    assert result["report"]["title"] == "Notion 竞品分析报告"
    assert agent.emit_progress.await_count >= 3


@pytest.mark.asyncio
async def test_review_agent_pause_reason_matches_progress_message():
    agent = ReviewAgent()
    agent.emit_progress = AsyncMock()
    ctx = _mock_ctx("review")

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
        result = await agent.run(state, ctx)

    pause_calls = [
        call for call in agent.emit_progress.await_args_list
        if call.kwargs.get("stage") == "await_human_decision"
    ]
    assert pause_calls
    pause = ReviewFailPausePolicy().build_pause(
        {"data": result, "control": {"revision_count": 0, "max_revisions": 3}, "runtime": {}},
        CompetitiveAnalysisTemplate.node("review"),
    )
    assert pause is not None
    assert pause_calls[-1].kwargs["message"] == pause.reason
