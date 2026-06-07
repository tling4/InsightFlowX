import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.report_agent import ReportAgent, ReportDraft
from app.core.runtime.context import AgentContext
from app.schemas.report import ReportSection


def _make_draft() -> ReportDraft:
    return ReportDraft(
        title="Test Report",
        executive_summary="Summary",
        sections=[
            ReportSection(
                heading="Overview",
                level=2,
                content="Content",
                source_refs=["https://example.com"],
            )
        ],
    )


def _mock_ctx() -> AgentContext:
    return AgentContext(
        workflow_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        node_id="report_writing",
        iteration=0,
        events=SimpleNamespace(
            emit=AsyncMock(),
            progress=AsyncMock(),
            stream_token=AsyncMock(),
        ),
    )


class TestReportAgent:
    @pytest.mark.asyncio
    async def test_partial_source_coverage_still_uses_llm(self):
        agent = ReportAgent()
        ctx = _mock_ctx()
        agent.log_and_broadcast = AsyncMock()
        agent.invoke_llm = AsyncMock(return_value=_make_draft())

        state = {
            "config": {"target_product": "Notion"},
            "raw_data": {
                "Notion": [{"url": "https://example.com", "title": "Notion"}],
                "阿里语雀": [],
            },
            "collection_errors": {
                "__source_coverage__": "Missing source coverage for: 阿里语雀",
            },
            "feature_matrix": {},
            "pricing_comparison": {},
            "user_sentiment": {},
            "swot": {},
        }

        with patch("app.agents.report_agent.llm_is_configured", return_value=True):
            result = await agent.run(state, ctx)

        agent.invoke_llm.assert_awaited_once()
        assert agent.invoke_llm.call_args.kwargs["stream_response"] is False
        payload = agent.invoke_llm.call_args.args[1]
        assert payload["source_coverage_issue"] == "Missing source coverage for: 阿里语雀"
        assert payload["collection_errors"]["__source_coverage__"] == "Missing source coverage for: 阿里语雀"
        assert result["report"]["title"] == "Test Report"
        assert len(result["report"]["sections"]) == 1
        assert "# Test Report" in result["report"]["full_markdown"]
        assert "## Overview" in result["report"]["full_markdown"]

    @pytest.mark.asyncio
    async def test_report_llm_failure_falls_back_without_failing_workflow(self):
        agent = ReportAgent()
        ctx = _mock_ctx()
        agent.log_and_broadcast = AsyncMock()
        agent.invoke_llm = AsyncMock(side_effect=ValueError("invalid structured output"))

        state = {
            "config": {"target_product": "Notion", "competitors": ["语雀"]},
            "raw_data": {
                "Notion": [{"url": "https://example.com", "title": "Notion"}],
                "语雀": [{"url": "https://example.com/yuque", "title": "语雀"}],
            },
            "feature_matrix": {},
            "pricing_comparison": {},
            "user_sentiment": {},
            "swot": {},
        }

        with patch("app.agents.report_agent.llm_is_configured", return_value=True):
            result = await agent.run(state, ctx)

        assert result["report"]["title"] == "Notion 竞品分析报告"
        assert result["report"]["sections"]
        assert "## 执行摘要" in result["report"]["full_markdown"]

    @pytest.mark.asyncio
    async def test_competitor_resolution_error_stays_insufficient(self):
        agent = ReportAgent()
        ctx = _mock_ctx()
        agent.log_and_broadcast = AsyncMock()
        agent.invoke_llm = AsyncMock(return_value=_make_draft())

        state = {
            "config": {"target_product": "Notion"},
            "raw_data": {
                "Notion": [{"url": "https://example.com", "title": "Notion"}],
            },
            "collection_errors": {
                "__competitor_resolution__": "Only resolved 1 valid competitor(s); at least 2 required before analysis.",
            },
        }

        with patch("app.agents.report_agent.llm_is_configured", return_value=True):
            result = await agent.run(state, ctx)

        agent.invoke_llm.assert_not_called()
        assert "资料不足" in result["report"]["title"]
        assert len(result["report"]["sections"]) == 7
        assert any(section["heading"] == "关键流程图" for section in result["report"]["sections"])

    def test_fallback_report_includes_mermaid_diagram_section(self):
        agent = ReportAgent()
        result = agent._fallback_report(
            "Claude Code",
            {
                "target_product": "Claude Code",
                "competitors": ["Cursor"],
                "focus_dimensions": ["目标用户", "使用场景", "核心问题"],
            },
            {
                "feature_matrix": {},
                "pricing_comparison": {},
                "user_sentiment": {},
                "swot": {},
                "competitor_role_analysis": {},
            },
            [],
        )

        assert any(section.heading == "关键流程图" for section in result.sections)
        assert "```mermaid" in result.full_markdown
        assert "Claude Code vs Cursor" in result.full_markdown
