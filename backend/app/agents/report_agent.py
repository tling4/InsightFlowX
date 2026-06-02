import time
import uuid
from datetime import datetime, date
from app.agents.base_agent import BaseAgent
from app.agents.agent_utils import llm_is_configured, raw_data_to_context
from app.services.event_service import EventLogger
from app.schemas.event import EventType
from app.schemas.report import ReportOutput, ReportSection, Citation
from pydantic import BaseModel


class ReportDraft(BaseModel):
    """LLM 返回的报告草稿结构。

    full_markdown 是最终展示用的完整 Markdown，
    sections 是拆开的章节列表供前端分段渲染。
    """
    title: str
    executive_summary: str
    sections: list[ReportSection]
    full_markdown: str


REPORT_SYSTEM_PROMPT = """你是专业中文商业分析报告撰写助手。请基于输入的结构化竞品分析和来源摘要写一份 Markdown 竞品分析报告。
要求：
- 只输出一个合法 JSON 对象，不要 Markdown 代码块，不要额外解释。
- 报告语言默认中文。
- 不要编造未在分析结果或来源中出现的事实；不确定时明确写"公开来源不足"。
- full_markdown 必须是完整 Markdown，包含标题、摘要、功能对比、定价、用户反馈、SWOT、建议。
- sections 每个对象包含 heading、level、content、source_refs。
JSON schema:
{
  "title": "...",
  "executive_summary": "...",
  "sections": [{"heading": "...", "level": 2, "content": "...", "source_refs": ["url"]}],
  "full_markdown": "# ...\\n\\n..."
}"""


class ReportAgent(BaseAgent):
    node_name = "report_writing"

    async def run(self, state: dict, event_logger: EventLogger, workflow_id: uuid.UUID) -> dict:
        """将结构化分析产物组装为 Markdown 竞品分析报告。

        LLM 可用时：调用 invoke_llm 生成报告草稿，再追加引用列表。
        LLM 不可用时：走 _fallback_report 用规则模板拼装。
        """
        config = state.get("config", {})
        if not isinstance(config, dict):
            config = {}
        target = config.get("target_product", "未知产品")
        raw_data = state.get("raw_data", {}) or {}
        collection_errors = state.get("collection_errors", {}) or {}
        source_coverage_issue = collection_errors.get("__source_coverage__")
        hard_collection_error = collection_errors.get("__competitor_resolution__")
        total_sources = sum(len(items) for items in raw_data.values()) if isinstance(raw_data, dict) else 0

        await self.log_and_broadcast(event_logger, EventType.NODE_START, {
            "input_summary": {"phase": "writing", "target_product": target},
        }, workflow_id)

        start = time.time()

        # 引用在 LLM 调用前构建，因为 LLM 不负责 URL 去重和编号
        citations = self._build_citations(raw_data)
        if hard_collection_error or total_sources == 0:
            report = self._insufficient_report(
                target,
                hard_collection_error or "公开来源不足",
                citations,
            )
        elif llm_is_configured():
            draft = await self.invoke_llm(
                REPORT_SYSTEM_PROMPT,
                {
                    "config": config,
                    "feature_matrix": state.get("feature_matrix"),
                    "pricing_comparison": state.get("pricing_comparison"),
                    "user_sentiment": state.get("user_sentiment"),
                    "swot": state.get("swot"),
                    "sources_by_product": raw_data_to_context(raw_data, max_items_per_product=4),
                    "collection_errors": collection_errors,
                    "source_coverage_issue": source_coverage_issue,
                },
                ReportDraft,
                event_logger, workflow_id, "report_writing",
                request_meta={"target_product": target},
            )
            await self.log_and_broadcast(event_logger, EventType.LLM_RESPONSE, {
                "model_task": "report_writing",
                "sections_count": len(draft.sections),
            }, workflow_id)
            report = ReportOutput(
                title=draft.title,
                executive_summary=draft.executive_summary,
                sections=draft.sections,
                citations=citations,
                # LLM 生成的 markdown 不包含引用，追加到末尾
                full_markdown=self._append_citations(draft.full_markdown, citations),
                generated_at=datetime.utcnow(),
            )
        else:
            report = self._fallback_report(target, config, state, citations)

        duration_ms = int((time.time() - start) * 1000)

        await self.log_and_broadcast(event_logger, EventType.NODE_COMPLETE, {
            "output_summary": {
                "sections_count": len(report.sections),
                "citations_count": len(report.citations),
            },
            "duration_ms": duration_ms,
        }, workflow_id)

        return {
            "report": report.model_dump(mode="json"),
            "current_phase": "writing",
        }

    def _insufficient_report(self, target: str, reason: str, citations: list[Citation]) -> ReportOutput:
        title = f"{target} 竞品分析报告（资料不足，未完成）"
        executive_summary = (
            "本次工作流未解析出足够明确的竞品实体，无法生成可交付的竞品分析结论。"
            f"原因：{reason}"
        )
        sections = [
            ReportSection(
                heading="未完成原因",
                level=2,
                content="竞品必须是明确的产品、品牌或服务实体；品类描述、用户自然语言片段、文章标题或媒体来源不能作为竞品。",
                source_refs=[],
            ),
            ReportSection(
                heading="建议",
                level=2,
                content="请补充明确竞品名称，或重新运行竞品推荐后再生成报告。",
                source_refs=[],
            ),
        ]
        markdown = "\n\n".join([
            f"# {title}",
            "## 执行摘要",
            executive_summary,
            "## 未完成原因",
            sections[0].content,
            "## 建议",
            sections[1].content,
        ])
        markdown = self._append_citations(markdown, citations)
        return ReportOutput(
            title=title,
            executive_summary=executive_summary,
            sections=sections,
            citations=citations,
            full_markdown=markdown,
            generated_at=datetime.utcnow(),
        )

    def _build_citations(self, raw_data: dict) -> list[Citation]:
        """从原始搜索结果为每个唯一 URL 生成编号引用。

        按产品遍历，同一 URL 只取首次出现的 title，用递增序号编号。
        上限 20 条，防止引用列表过长撑爆 token。
        """
        citations: list[Citation] = []
        seen: set[str] = set()
        for items in raw_data.values():
            for item in items:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                citations.append(Citation(
                    index=len(citations) + 1,
                    url=url,
                    title=item.get("title") or url,
                    access_date=date.today(),
                ))
                if len(citations) >= 20:
                    return citations
        return citations

    def _append_citations(self, markdown: str, citations: list[Citation]) -> str:
        """在 Markdown 末尾追加「参考来源」章节。

        与 LLM 生成的正文分离，确保引用 URL 精确对应搜索结果，
        不受 LLM 幻觉影响。
        """
        if not citations:
            return markdown
        lines = [markdown.rstrip(), "", "## 参考来源"]
        for citation in citations:
            lines.append(f"{citation.index}. [{citation.title}]({citation.url})，访问日期：{citation.access_date.isoformat()}")
        return "\n".join(lines)

    def _fallback_report(self, target: str, config: dict, state: dict, citations: list[Citation]) -> ReportOutput:
        """无 LLM 时的规则报告：用模板将分析产物格式化为 Markdown。"""
        feature_matrix = state.get("feature_matrix") or {}
        pricing = state.get("pricing_comparison") or {}
        sentiment = state.get("user_sentiment") or {}
        swot = state.get("swot") or {}

        executive_summary = (
            f"本报告基于当前工作流中已采集和分析的结构化数据生成。"
            f"由于未配置可用 LLM 或外部来源不足，关于 {target} 的具体市场结论需要结合真实搜索结果复核。"
        )
        sections = [
            ReportSection(heading="功能对比", level=2, content=self._format_feature_matrix(feature_matrix), source_refs=[]),
            ReportSection(heading="定价对比", level=2, content=pricing.get("summary", "公开来源不足，暂无法确认定价差异。"), source_refs=[]),
            ReportSection(heading="用户反馈", level=2, content=self._format_sentiment(sentiment), source_refs=[]),
            ReportSection(heading="SWOT 分析", level=2, content=self._format_swot(swot), source_refs=[]),
            ReportSection(heading="建议", level=2, content="接入真实 LLM 和 Tavily API key 后，重新运行工作流以生成可用于决策的完整报告。", source_refs=[]),
        ]
        markdown_lines = [f"# {target} 竞品分析报告", "", "## 执行摘要", executive_summary, ""]
        for section in sections:
            markdown_lines.extend([f"{'#' * section.level} {section.heading}", section.content, ""])
        markdown = self._append_citations("\n".join(markdown_lines), citations)
        return ReportOutput(
            title=f"{target} 竞品分析报告",
            executive_summary=executive_summary,
            sections=sections,
            citations=citations,
            full_markdown=markdown,
            generated_at=datetime.utcnow(),
        )

    def _format_feature_matrix(self, data: dict) -> str:
        items = data.get("matrix", []) if isinstance(data, dict) else []
        if not items:
            return "暂无可确认的功能对比数据。"
        lines = []
        for item in items:
            products = item.get("products", {})
            product_text = "；".join(f"{name}: {value}" for name, value in products.items())
            lines.append(f"- {item.get('feature_name', '维度')}: {product_text}")
        return "\n".join(lines)

    def _format_sentiment(self, data: dict) -> str:
        per_product = data.get("per_product", {}) if isinstance(data, dict) else {}
        if not per_product:
            return "暂无足够用户反馈数据。"
        return "\n".join(
            f"- {product}: 正向 {scores.get('positive', 0)}，负向 {scores.get('negative', 0)}，中性 {scores.get('neutral', 0)}"
            for product, scores in per_product.items()
            if isinstance(scores, dict)
        )

    def _format_swot(self, data: dict) -> str:
        if not isinstance(data, dict):
            return "暂无 SWOT 数据。"
        labels = [
            ("优势", "strengths"),
            ("劣势", "weaknesses"),
            ("机会", "opportunities"),
            ("威胁", "threats"),
        ]
        parts = []
        for label, key in labels:
            values = data.get(key, []) or ["公开来源不足"]
            parts.append(f"**{label}**：" + "；".join(values))
        return "\n\n".join(parts)
