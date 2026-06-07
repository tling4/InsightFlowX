import time
from datetime import datetime, date
from app.agents.base_agent import BaseAgent
from app.agents.agent_utils import llm_is_configured, raw_data_to_context
from app.core.runtime.context import AgentContext
from app.schemas.event import EventType
from app.schemas.report import ReportOutput, ReportSection, Citation
from pydantic import BaseModel


class ReportDraft(BaseModel):
    """LLM 返回的报告草稿结构。

    Markdown 由后端根据 sections 确定性渲染，避免模型重复输出同一份报告。
    """
    title: str
    executive_summary: str
    sections: list[ReportSection]


REPORT_SYSTEM_PROMPT = """你是专业中文商业分析报告撰写助手。请基于输入的结构化竞品分析和来源摘要写一份 Markdown 竞品分析报告。
要求：
- 只输出一个合法 JSON 对象，不要 Markdown 代码块，不要额外解释。
- 报告语言默认中文。
- 不要编造未在分析结果或来源中出现的事实；不确定时明确写"当前采集结果未覆盖"，不要断言公开来源不存在。
- 报告不是简单复述“别人做了什么”，而是要回答“这对当前项目有什么用”。
- 结论必须服务于用户要解决的问题；如果 config.extra_requirements 中包含业务问题、决策场景、预期用途或信息来源偏好，必须优先吸收。
- 优先用“用户-场景-问题-解决方案-支撑点”框架理解产品定位，并尽量说明其是否成立。
- 报告要围绕用户实际选择的竞品来写，不要假设一定存在完整的“五类竞品”。
- 如果 config.competitor_groups 中已有角色判断，请将其视为对已选竞品的角色标签，而不是要求每个标签都必须有对象。
- 如果用户只分析 1 个竞品，也可以成立；需要说明这个竞品在当前细分市场里更接近什么角色，以及这种选择对本次分析意味着什么。
- 如果来源里能支撑，继续拆解上市节奏、平台组合、内容策略、投放动作和商业结果；如果证据不足，要明确指出边界。
- sections 必须至少包含以下章节：
  1. 分析目标
  2. 结论先行
  3. 产品定位判断
  4. 竞品范围与角色判断
  5. 关键发现
  6. 成功与失败原因拆解
  7. 上市与增长拆解
  8. 关键流程图
  9. 对当前项目的启示
  10. 行动建议
- sections 每个对象包含 heading、level、content、source_refs。
- “关键发现”和“行动建议”必须可执行，避免空泛表述。
- “关键流程图”的 content 优先输出 Mermaid 流程图；如果证据不足，也要明确写出流程假设与证据边界。
- 如果当前采集结果不足以支撑结论，要明确指出证据边界，不要假装确定。
JSON schema:
{
  "title": "...",
  "executive_summary": "...",
  "sections": [{"heading": "...", "level": 2, "content": "...", "source_refs": ["url"]}]
}"""


class ReportAgent(BaseAgent):
    node_name = "report_writing"

    async def run(self, state: dict, ctx: AgentContext) -> dict:
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

        await self.log_and_broadcast(ctx, EventType.NODE_START, {
            "input_summary": {"phase": "writing", "target_product": target},
        })
        await self.emit_progress(
            ctx,
            stage="outline_report",
            message="正在组织报告结构，并准备执行摘要、主体章节与引用列表。",
        )

        start = time.time()

        # 引用在 LLM 调用前构建，因为 LLM 不负责 URL 去重和编号
        citations = self._build_citations(raw_data)
        await self.emit_progress(
            ctx,
            stage="prepare_citations",
            message=f"已整理 {len(citations)} 条候选引用，准备写入报告上下文。",
        )
        if hard_collection_error or total_sources == 0:
            await self.emit_progress(
                ctx,
                stage="insufficient_sources",
                message=f"当前无可用采集结果，将生成说明性报告而不是完整交付稿。原因：{hard_collection_error or '当前采集结果不足'}",
                level="warning",
            )
            report = self._insufficient_report(
                target,
                hard_collection_error or "当前采集结果不足",
                citations,
            )
        elif llm_is_configured():
            await self.emit_progress(
                ctx,
                stage="draft_report",
                message="正在撰写执行摘要，并整合功能、定价、反馈与 SWOT 内容。",
            )
            try:
                draft = await self.invoke_llm(
                    REPORT_SYSTEM_PROMPT,
                    {
                        "config": config,
                        "feature_matrix": state.get("feature_matrix"),
                        "pricing_comparison": state.get("pricing_comparison"),
                        "user_sentiment": state.get("user_sentiment"),
                        "positioning_analysis": state.get("positioning_analysis"),
                        "swot": state.get("swot"),
                        "competitor_role_analysis": state.get("competitor_role_analysis"),
                        "gtm_analysis": state.get("gtm_analysis"),
                        "sources_by_product": raw_data_to_context(raw_data, max_items_per_product=4),
                        "collection_errors": collection_errors,
                        "source_coverage_issue": source_coverage_issue,
                    },
                    ReportDraft,
                    ctx, "report_writing",
                    request_meta={"target_product": target},
                    stream_response=False,
                )
                await self.log_and_broadcast(ctx, EventType.LLM_RESPONSE, {
                    "model_task": "report_writing",
                    "sections_count": len(draft.sections),
                })
                report = ReportOutput(
                    title=draft.title,
                    executive_summary=draft.executive_summary,
                    sections=draft.sections,
                    citations=citations,
                    full_markdown=self._render_markdown(draft.title, draft.executive_summary, draft.sections, citations),
                    generated_at=datetime.utcnow(),
                )
                await self.emit_progress(
                    ctx,
                    stage="report_draft_ready",
                    message=f"报告草稿已生成，当前包含 {len(draft.sections)} 个主要章节。",
                    level="success",
                )
            except Exception as exc:
                await self.emit_progress(
                    ctx,
                    stage="fallback_report",
                    message=f"模型报告生成失败，已使用现有结构化分析生成模板报告：{str(exc)[:160]}",
                    level="warning",
                )
                report = self._fallback_report(target, config, state, citations)
        else:
            await self.emit_progress(
                ctx,
                stage="fallback_report",
                message="未使用实时模型写作，当前将基于结构化结果生成模板化报告。",
                level="warning",
            )
            report = self._fallback_report(target, config, state, citations)

        duration_ms = int((time.time() - start) * 1000)
        await self.emit_progress(
            ctx,
            stage="finalize_report",
            message=f"报告整理完成，已附加 {len(report.citations)} 条引用并输出 Markdown 成稿。",
            level="success",
        )

        await self.log_and_broadcast(ctx, EventType.NODE_COMPLETE, {
            "output_summary": {
                "sections_count": len(report.sections),
                "citations_count": len(report.citations),
            },
            "duration_ms": duration_ms,
        })

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
                heading="分析目标",
                level=2,
                content="当前分析未形成可执行的问题定义，暂时无法将竞品信息转化为对项目有用的判断。",
                source_refs=[],
            ),
            ReportSection(
                heading="结论先行",
                level=2,
                content=f"现阶段最关键的问题不是继续堆积信息，而是先补齐明确竞品对象与分析目标。当前无法支持有效结论，原因：{reason}",
                source_refs=[],
            ),
            ReportSection(
                heading="竞品范围与角色判断",
                level=2,
                content="当前尚未形成足够明确的竞品列表，因此无法判断这些对象分别属于核心、标杆、潜力、替代或避坑中的哪一类。",
                source_refs=[],
            ),
            ReportSection(
                heading="成功与失败原因拆解",
                level=2,
                content="竞品必须是明确的产品、品牌或服务实体；品类描述、用户自然语言片段、文章标题或媒体来源不能作为竞品，否则无法形成有效拆解。",
                source_refs=[],
            ),
            ReportSection(
                heading="上市与增长拆解",
                level=2,
                content="当前采集结果未覆盖相关维度，尚不能有效判断其上市节奏、平台组合、内容策略、投放动作与商业结果。",
                source_refs=[],
            ),
            ReportSection(
                heading="关键流程图",
                level=2,
                content=(
                    "当前缺少足够证据来还原可靠流程图。\n\n"
                    "```mermaid\n"
                    "flowchart TD\n"
                    "  A[补充明确竞品对象] --> B[补充公开来源]\n"
                    "  B --> C[确认分析目标与场景]\n"
                    "  C --> D[重新生成正式竞品分析]\n"
                    "```\n\n"
                    "说明：该图只表示当前补齐信息的推荐步骤，不代表真实用户流程。"
                ),
                source_refs=[],
            ),
            ReportSection(
                heading="行动建议",
                level=2,
                content="请先补充明确竞品名称、分析目标和预期决策场景，再重新运行工作流生成正式报告。",
                source_refs=[],
            ),
        ]
        markdown = "\n\n".join([
            f"# {title}",
            "## 分析目标",
            sections[0].content,
            "## 结论先行",
            sections[1].content,
            "## 竞品范围与角色判断",
            sections[2].content,
            "## 成功与失败原因拆解",
            sections[3].content,
            "## 上市与增长拆解",
            sections[4].content,
            "## 关键流程图",
            sections[5].content,
            "## 行动建议",
            sections[6].content,
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

    def _render_markdown(
        self,
        title: str,
        executive_summary: str,
        sections: list[ReportSection],
        citations: list[Citation],
    ) -> str:
        """Render the final Markdown from structured sections without LLM duplication."""
        lines = [f"# {title}", "", "## 执行摘要", executive_summary, ""]
        for section in sections:
            level = min(max(section.level, 2), 6)
            lines.extend([f"{'#' * level} {section.heading}", section.content, ""])
        return self._append_citations("\n".join(lines).rstrip(), citations)

    def _fallback_report(self, target: str, config: dict, state: dict, citations: list[Citation]) -> ReportOutput:
        """无 LLM 时的规则报告：用模板将分析产物格式化为 Markdown。"""
        feature_matrix = state.get("feature_matrix") or {}
        pricing = state.get("pricing_comparison") or {}
        sentiment = state.get("user_sentiment") or {}
        positioning = state.get("positioning_analysis") or {}
        swot = state.get("swot") or {}
        role_analysis = state.get("competitor_role_analysis") or {}
        gtm_analysis = state.get("gtm_analysis") or {}
        problem = self._extract_problem_statement(config)
        scope = self._format_scope(config, role_analysis)

        executive_summary = (
            f"本报告围绕“{problem}”生成。"
            f"由于未配置可用 LLM 或外部来源不足，关于 {target} 的具体市场结论仍需结合真实搜索结果复核，"
            "但现有结果已可用于整理可参考做法、验证初步判断和识别明显风险。"
        )
        sections = [
            ReportSection(heading="分析目标", level=2, content=problem, source_refs=[]),
            ReportSection(heading="结论先行", level=2, content=self._build_top_conclusion(target, config, state), source_refs=[]),
            ReportSection(heading="产品定位判断", level=2, content=self._build_positioning_judgment(config, positioning), source_refs=[]),
            ReportSection(heading="竞品范围与角色判断", level=2, content=scope, source_refs=[]),
            ReportSection(heading="关键发现", level=2, content=self._format_key_findings(feature_matrix, pricing, sentiment), source_refs=[]),
            ReportSection(heading="成功与失败原因拆解", level=2, content=self._format_reason_analysis(swot), source_refs=[]),
            ReportSection(heading="上市与增长拆解", level=2, content=self._build_go_to_market_analysis(config, gtm_analysis), source_refs=[]),
            ReportSection(heading="关键流程图", level=2, content=self._build_key_flow_diagram(target, config), source_refs=[]),
            ReportSection(heading="对当前项目的启示", level=2, content=self._build_project_implications(config), source_refs=[]),
            ReportSection(heading="行动建议", level=2, content=self._build_action_recommendations(target), source_refs=[]),
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

    def _extract_problem_statement(self, config: dict) -> str:
        extra = (config.get("extra_requirements") or "").strip() if isinstance(config, dict) else ""
        target = config.get("target_product", "当前目标产品") if isinstance(config, dict) else "当前目标产品"
        if extra:
            return extra
        focus = "、".join((config.get("focus_dimensions") or [])[:4]) if isinstance(config, dict) else ""
        if focus:
            return f"围绕 {target} 的 {focus} 等关键维度，寻找可参考做法并验证当前产品判断。"
        return f"围绕 {target} 梳理可参考做法、验证已有判断，并输出可用于决策的结论。"

    def _format_scope(self, config: dict, role_analysis: dict | None = None) -> str:
        competitors = config.get("competitors") or [] if isinstance(config, dict) else []
        groups = config.get("competitor_groups") or {} if isinstance(config, dict) else {}
        profile = config.get("product_profile") or {} if isinstance(config, dict) else {}
        basis = profile.get("competition_basis") or []
        excludes = profile.get("exclude_relations") or []
        parts = []
        if competitors:
            parts.append("纳入分析对象：" + "、".join(competitors))
        role_summary = self._format_competitor_roles(role_analysis or groups)
        if role_summary:
            parts.append(role_summary)
        if basis:
            parts.append("纳入依据：" + "；".join(basis))
        if excludes:
            parts.append("明确排除：" + "；".join(excludes))
        if not parts:
            return "当前竞品范围依据有限，建议先明确真正要分析的竞品，以及这些竞品在当前细分市场中的角色判断。"
        return "\n".join(f"- {part}" for part in parts)

    def _build_top_conclusion(self, target: str, config: dict, state: dict) -> str:
        competitors = config.get("competitors") or [] if isinstance(config, dict) else []
        dimensions = config.get("focus_dimensions") or [] if isinstance(config, dict) else []
        role_hint = self._summarize_primary_role(
            state.get("competitor_role_analysis") or config.get("competitor_groups") or {}
            if isinstance(config, dict) else {}
        )
        has_sources = bool(state.get("raw_data"))
        if competitors and dimensions and has_sources:
            return (
                f"当前分析已经围绕 {target} 与 {'、'.join(competitors[:3])} 的对比，"
                f"在 {'、'.join(dimensions[:3])} 等维度形成初步判断。"
                f"{role_hint}"
                "后续决策重点应放在提炼可复制做法、识别高风险做法，以及明确哪些结论可直接服务当前项目。"
            )
        return f"当前可形成的是方向性判断，而非最终结论；建议把重点放在补足证据和收敛分析目标。"

    def _build_positioning_judgment(self, config: dict, positioning: dict | None = None) -> str:
        target = config.get("target_product", "该产品") if isinstance(config, dict) else "该产品"
        dimensions = config.get("focus_dimensions") or [] if isinstance(config, dict) else []
        extra = (config.get("extra_requirements") or "").strip() if isinstance(config, dict) else ""
        positioning_dims = [d for d in dimensions if d in {"目标用户", "使用场景", "核心问题", "解决方案", "支撑点", "市场定位"}]
        parts = [
            f"本次分析默认将 {target} 视为一个需要回答“为谁、在什么场景下、解决什么问题”的产品，而不是仅比较功能参数。"
        ]
        if positioning_dims:
            parts.append("当前重点定位维度：" + "、".join(positioning_dims) + "。")
        if extra:
            parts.append("与定位相关的补充背景：" + extra)
        if isinstance(positioning, dict) and positioning.get("summary"):
            parts.append("当前结构化定位判断：" + str(positioning.get("summary")))
        parts.append("后续结论将优先判断其用户价值是否成立、场景是否清晰、问题是否真实、方案是否有效、支撑点是否可信。")
        return "\n".join(parts)

    def _format_key_findings(self, feature_matrix: dict, pricing: dict, sentiment: dict) -> str:
        parts = [
            "### 功能与体验",
            self._format_feature_matrix(feature_matrix),
            "",
            "### 定价与商业化",
            pricing.get("summary", "当前采集结果未覆盖，暂无法确认定价差异。"),
            "",
            "### 用户反馈",
            self._format_sentiment(sentiment),
        ]
        return "\n".join(parts)

    def _format_reason_analysis(self, swot: dict) -> str:
        formatted = self._format_swot(swot)
        if formatted == "暂无 SWOT 数据。":
            return "当前采集结果不足，尚无法稳定拆解成功与失败原因，建议补充检索后再继续判断。"
        return (
            "以下拆解用于回答“为什么这些竞品做得好/做得差”，而不只是复述它们做了什么：\n\n"
            f"{formatted}"
        )

    def _build_go_to_market_analysis(self, config: dict, gtm_analysis: dict | None = None) -> str:
        dimensions = config.get("focus_dimensions") or [] if isinstance(config, dict) else []
        extra = (config.get("extra_requirements") or "").strip() if isinstance(config, dict) else ""
        launch_dims = [d for d in dimensions if d in {"上市节奏", "平台组合", "内容策略", "投放动作", "商业结果"}]
        if isinstance(gtm_analysis, dict) and gtm_analysis.get("summary"):
            return str(gtm_analysis.get("summary"))
        if launch_dims:
            return (
                "本次分析将进一步关注以下上市与增长问题："
                + "、".join(launch_dims)
                + "。如果来源允许，应重点判断其节奏铺排、渠道分工、内容概念、投放结构与结果复盘。"
            )
        if "上市" in extra or "营销" in extra or "增长" in extra:
            return (
                "用户已明确提出上市或增长相关诉求。后续应重点观察其上市节奏、渠道策略、内容打法、投放方式与商业结果，"
                "并区分哪些经验可复用、哪些只适用于特定资源条件。"
            )
        return "当前更偏向产品与竞品判断，上市与增长拆解暂不作为主结论，但若来源出现明显证据，仍应纳入辅助判断。"

    def _build_project_implications(self, config: dict) -> str:
        dimensions = config.get("focus_dimensions") or [] if isinstance(config, dict) else []
        competitors = config.get("competitors") or [] if isinstance(config, dict) else []
        role_hint = self._summarize_primary_role(config.get("competitor_groups") or {} if isinstance(config, dict) else {})
        if dimensions:
            return (
                "建议仅保留与当前项目直接相关的判断，并优先用于以下决策："
                f"{'、'.join(dimensions[:4])}。"
                + (f" 当前实际分析对象为 {'、'.join(competitors[:3])}。{role_hint}" if competitors else "")
                + "对于与问题无关的信息，不应进入最终结论。"
            )
        return "建议优先提炼能直接影响产品定义、优先级排序和验证路径的判断，避免信息堆积。"

    def _build_key_flow_diagram(self, target: str, config: dict) -> str:
        competitors = config.get("competitors") or [] if isinstance(config, dict) else []
        primary = competitors[0] if competitors else "代表性竞品"
        problem = self._extract_problem_statement(config)
        lines = [
            "下面用流程图表达本次竞品分析的最小判断路径，帮助用户快速理解“从问题到策略”的分析链路。",
            "",
            "```mermaid",
            "flowchart TD",
            f'  A["明确问题\\n{problem[:36] + ("..." if len(problem) > 36 else "")}"] --> B["选择分析对象\\n{target} vs {primary}"]',
            '  B --> C["拆解产品定位\\n用户/场景/问题/方案/支撑点"]',
            '  C --> D["复盘增长打法\\n节奏/渠道/内容/投放/结果"]',
            '  D --> E["提炼可复用结论\\n哪些值得学，哪些要避坑"]',
            "```",
            "",
            "说明：该图是本次分析报告的结构化阅读路径，不等同于真实产品的用户操作流程；如果后续补充了更充分的证据，可以再替换为更具体的用户流程图或商业流程图。",
        ]
        return "\n".join(lines)

    def _build_action_recommendations(self, target: str) -> str:
        return (
            f"1. 将 {target} 当前要解决的问题写成一句清晰判断，并据此筛掉无关信息。\n"
            "2. 明确目标用户、关键场景和核心问题，判断这是痛点、痒点还是爽点。\n"
            "3. 先确认当前真正要分析的是哪些竞品，再判断它们分别更接近核心、标杆、潜力、替代还是避坑角色。\n"
            "4. 所有关键判断都尽量绑定来源与证据边界，避免把主观感受当作结论。\n"
            "5. 如果业务目标涉及上市或增长，再单独补看节奏、渠道、内容、投放与结果，不要和产品定位混为一谈。\n"
            "6. 最终只保留能直接指导当前项目决策的结论与建议。"
        )

    def _format_competitor_roles(self, groups: dict) -> str:
        if not isinstance(groups, dict):
            return ""
        if "items" in groups and isinstance(groups.get("items"), list):
            parts = []
            labels = {
                "core": "核心竞品",
                "benchmark": "标杆竞品",
                "potential": "潜力竞品",
                "substitute": "替代竞品",
                "pitfall": "避坑竞品",
                "unknown": "待确认角色",
            }
            for item in groups.get("items", []):
                if not isinstance(item, dict) or not item.get("product"):
                    continue
                role = labels.get(item.get("role"), item.get("role", "unknown"))
                reason = item.get("reason", "")
                parts.append(f"{item['product']}：{role}" + (f"（{reason}）" if reason else ""))
            if parts:
                return "角色判断：" + "；".join(parts)
        labels = {
            "core": "核心竞品",
            "benchmark": "标杆竞品",
            "potential": "潜力竞品",
            "substitute": "替代竞品",
            "pitfall": "避坑竞品",
        }
        parts = []
        for key, label in labels.items():
            values = groups.get(key) or []
            if values:
                parts.append(f"{label}：" + "、".join(values))
        if not parts:
            return ""
        return "角色判断：" + "；".join(parts)

    def _summarize_primary_role(self, groups: dict) -> str:
        if not isinstance(groups, dict):
            return ""
        if "items" in groups and isinstance(groups.get("items"), list):
            role_order = [
                ("core", "这些对象更接近核心竞品，应重点比较可直接影响当前项目决策的能力与策略。"),
                ("benchmark", "这些对象更接近标杆竞品，更适合作为方向参考与方法借鉴。"),
                ("potential", "这些对象更接近潜力竞品，适合用来观察新打法和差异化机会。"),
                ("substitute", "这些对象更接近替代竞品，适合帮助识别更大层面的需求替代关系。"),
                ("pitfall", "这些对象更接近避坑竞品，适合帮助识别高风险做法与反面经验。"),
            ]
            roles = {item.get("role") for item in groups.get("items", []) if isinstance(item, dict)}
            for key, text in role_order:
                if key in roles:
                    return text
            return ""
        role_order = [
            ("core", "这些对象更接近核心竞品，应重点比较可直接影响当前项目决策的能力与策略。"),
            ("benchmark", "这些对象更接近标杆竞品，更适合作为方向参考与方法借鉴。"),
            ("potential", "这些对象更接近潜力竞品，适合用来观察新打法和差异化机会。"),
            ("substitute", "这些对象更接近替代竞品，适合帮助识别更大层面的需求替代关系。"),
            ("pitfall", "这些对象更接近避坑竞品，适合帮助识别高风险做法与反面经验。"),
        ]
        for key, text in role_order:
            if groups.get(key):
                return text
        return ""

    def _format_feature_matrix(self, data: dict) -> str:
        items = data.get("matrix", []) if isinstance(data, dict) else []
        if not items:
            return "暂无可确认的功能对比数据。"
        lines = []
        for item in items:
            product_text = "当前采集结果未覆盖"
            comparisons = item.get("comparisons", [])
            if isinstance(comparisons, list) and comparisons:
                product_text = "；".join(
                    f"{comp.get('product', '产品')}：{comp.get('difference_summary') or comp.get('support_level') or '未确认'}"
                    for comp in comparisons
                    if isinstance(comp, dict)
                )
            else:
                products = item.get("products", {})
                if isinstance(products, dict):
                    product_text = "；".join(f"{name}：{value}" for name, value in products.items())
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
            values = data.get(key, []) or ["当前采集结果未覆盖"]
            parts.append(f"**{label}**：" + "；".join(values))
        return "\n\n".join(parts)
