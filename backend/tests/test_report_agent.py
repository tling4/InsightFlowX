import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.report_agent import (
    ANALYSIS_HEADINGS,
    DECISION_HEADINGS,
    SUPPLEMENT_HEADINGS,
    ReportAgent,
    ReportDraft,
    ReportSectionBatch,
)
from app.core.runtime.context import AgentContext
from app.schemas.report import ReportSection


def _make_sections(headings: list[str]) -> list[ReportSection]:
    return [
        ReportSection(
            heading=heading,
            level=2,
            content=(
                "流程说明：\n\n```mermaid\nflowchart LR\n  A[开始] --> B[结束]\n```\n\n证据边界说明。"
                if heading == "关键流程图"
                else f"{heading} content"
            ),
            source_refs=["https://example.com"],
        )
        for heading in headings
    ]


def _make_batches():
    return [
        ReportSectionBatch(sections=_make_sections(ANALYSIS_HEADINGS)),
        ReportDraft(
            title="Test Report",
            executive_summary="Summary",
            sections=_make_sections(DECISION_HEADINGS),
        ),
        ReportSectionBatch(sections=_make_sections(SUPPLEMENT_HEADINGS)),
    ]


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
        agent.invoke_structured_llm = AsyncMock(side_effect=_make_batches())

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

        assert agent.invoke_structured_llm.await_count == 3
        payload = agent.invoke_structured_llm.call_args_list[0].args[1]
        assert payload["source_coverage_issue"] == "Missing source coverage for: 阿里语雀"
        assert payload["collection_errors"]["__source_coverage__"] == "Missing source coverage for: 阿里语雀"
        assert result["report"]["title"] == "Test Report"
        assert len(result["report"]["sections"]) == 10
        assert "# Test Report" in result["report"]["full_markdown"]
        assert "## 行动建议" in result["report"]["full_markdown"]

    @pytest.mark.asyncio
    async def test_report_batch_failure_is_not_converted_to_fallback(self):
        agent = ReportAgent()
        ctx = _mock_ctx()
        agent.log_and_broadcast = AsyncMock()
        agent.invoke_structured_llm = AsyncMock(
            side_effect=[
                ReportSectionBatch(sections=_make_sections(ANALYSIS_HEADINGS)),
                ValueError("invalid structured output"),
            ]
        )

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
            with pytest.raises(ValueError, match="invalid structured output"):
                await agent.run(state, ctx)

        assert agent.invoke_structured_llm.await_count == 2

    @pytest.mark.asyncio
    async def test_missing_llm_does_not_deliver_generic_fallback(self):
        agent = ReportAgent()
        ctx = _mock_ctx()
        agent.log_and_broadcast = AsyncMock()
        state = {
            "config": {"target_product": "Notion"},
            "raw_data": {"Notion": [{"url": "https://example.com", "title": "Notion"}]},
        }

        with patch("app.agents.report_agent.llm_is_configured", return_value=False):
            with pytest.raises(RuntimeError, match="未生成通用 fallback 报告"):
                await agent.run(state, ctx)

    @pytest.mark.asyncio
    async def test_competitor_resolution_error_stays_insufficient(self):
        agent = ReportAgent()
        ctx = _mock_ctx()
        agent.log_and_broadcast = AsyncMock()
        agent.invoke_structured_llm = AsyncMock(return_value=_make_draft())

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

        agent.invoke_structured_llm.assert_not_called()
        assert "资料不足" in result["report"]["title"]
        assert len(result["report"]["sections"]) == 7
        assert any(section["heading"] == "关键流程图" for section in result["report"]["sections"])

    def test_validate_sections_rejects_missing_heading(self):
        agent = ReportAgent()

        with pytest.raises(ValueError, match="headings mismatch"):
            agent._validate_sections(
                _make_sections(ANALYSIS_HEADINGS[:-1]),
                ANALYSIS_HEADINGS,
                "analysis",
            )

    def test_normalize_section_prevents_inline_heading_style_leak(self):
        agent = ReportAgent()
        section = ReportSection(
            heading="成功与失败原因拆解",
            level=1,
            content="### 成功经验可复用拆解1. 第一项；2. 第二项。### 失败教训需规避拆解1. 第三项。",
            source_refs=[],
        )

        normalized = agent._normalize_section(section)

        assert normalized.level == 2
        assert "###" not in normalized.content
        assert "**成功经验可复用拆解**\n\n1. 第一项" in normalized.content
        assert "\n\n2. 第二项" in normalized.content
        assert "**失败教训需规避拆解**\n\n1. 第三项" in normalized.content

    def test_normalize_section_separates_standalone_bold_subheadings(self):
        agent = ReportAgent()
        section = ReportSection(
            heading="产品定位判断",
            level=2,
            content=(
                "定位判断正文。\n"
                "**定位成立的核心支撑点**\n"
                "1. 第一项。\n\n"
                "2. 第二项。\n"
                "**当前定位下的核心覆盖场景**\n"
                "1. 场景一。"
            ),
            source_refs=[],
        )

        normalized = agent._normalize_section(section)

        assert "定位判断正文。\n\n**定位成立的核心支撑点**\n\n1. 第一项。" in normalized.content
        assert "2. 第二项。\n\n**当前定位下的核心覆盖场景**\n\n1. 场景一。" in normalized.content

    def test_normalize_mermaid_repairs_collapsed_fences_and_edges(self):
        agent = ReportAgent()
        section = ReportSection(
            heading="关键流程图",
            level=2,
            content=(
                "流程说明：```mermaidflowchart LR    A[开始] --> B[检查]    "
                "B --> C[结束]``` 证据边界说明。"
            ),
            source_refs=[],
        )

        normalized = agent._normalize_section(section)
        agent._validate_mermaid_section(normalized)

        assert "\n\n```mermaid\nflowchart LR" in normalized.content
        assert "\n  B --> C[结束]\n```" in normalized.content

    def test_validate_mermaid_rejects_unbalanced_diagram(self):
        agent = ReportAgent()
        section = ReportSection(
            heading="关键流程图",
            level=2,
            content="```mermaid\nflowchart LR\n  A[开始] --> B[结束\n```",
            source_refs=[],
        )

        with pytest.raises(ValueError, match="unbalanced delimiters"):
            agent._validate_mermaid_section(section)

    def test_validate_sections_rejects_remaining_markdown_heading(self):
        agent = ReportAgent()
        sections = _make_sections(ANALYSIS_HEADINGS)
        sections[0] = sections[0].model_copy(
            update={"content": "正文中意外出现 ### 未规范化标题"}
        )

        with pytest.raises(ValueError, match="unsupported Markdown heading syntax"):
            agent._validate_sections(sections, ANALYSIS_HEADINGS, "analysis")

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
