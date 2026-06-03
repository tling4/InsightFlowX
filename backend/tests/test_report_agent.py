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
        full_markdown="# Test Report\n\nContent",
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
        payload = agent.invoke_llm.call_args.args[1]
        assert payload["source_coverage_issue"] == "Missing source coverage for: 阿里语雀"
        assert payload["collection_errors"]["__source_coverage__"] == "Missing source coverage for: 阿里语雀"
        assert result["report"]["title"] == "Test Report"
        assert len(result["report"]["sections"]) == 1

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
        assert len(result["report"]["sections"]) == 2
