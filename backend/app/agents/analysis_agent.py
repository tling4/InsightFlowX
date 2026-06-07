import time
from datetime import datetime

from pydantic import BaseModel

from app.agents.agent_utils import llm_is_configured, raw_data_to_context
from app.agents.base_agent import BaseAgent
from app.core.runtime.context import AgentContext
from app.schemas.competitor_role import CompetitorRoleAnalysis, CompetitorRoleItem
from app.schemas.evidence import EvidenceRef
from app.schemas.event import EventType
from app.schemas.feature import FeatureComparison, FeatureItem, FeatureMatrix
from app.schemas.gtm import GTMAnalysis, GTMSection
from app.schemas.positioning import PositioningAnalysis, PositioningDimension
from app.schemas.pricing import PricingComparison
from app.schemas.sentiment import UserSentimentAnalysis
from app.schemas.swot import SWOTAnalysis


class AnalysisBundle(BaseModel):
    feature_matrix: FeatureMatrix
    pricing_comparison: PricingComparison
    user_sentiment: UserSentimentAnalysis
    positioning_analysis: PositioningAnalysis
    swot: SWOTAnalysis
    competitor_role_analysis: CompetitorRoleAnalysis
    gtm_analysis: GTMAnalysis


SWOT_SYSTEM_PROMPT = """你是资深竞品分析师。请只基于公开来源，为目标产品输出 SWOTAnalysis JSON。
要求：
- 只返回合法 JSON 对象，不要 Markdown，不要解释。
- strengths / weaknesses / opportunities / threats 各输出 2-4 条。
- source_refs 使用 {\"要点\": [\"url1\", \"url2\"]} 结构。
- 不要编造未在来源中体现的事实；来源不足时明确写成保守结论。
"""

FEATURE_SYSTEM_PROMPT = """你是资深竞品分析师。请只基于公开来源输出单个分析维度的 FeatureItem JSON。
要求：
- 只返回合法 JSON 对象，不要 Markdown，不要解释。
- 顶层必须直接包含 module、feature_name、comparisons；不要使用 FeatureItem / feature_item 外层字段，也不要将对象包在数组中。
- feature_name 必须与 requested_dimension 完全一致。
- comparisons[] 需包含 product、support_level、difference_summary、evidence_refs。
- evidence_refs 必须是对象数组，每项格式为 {"url": "...", "title": "...", "snippet": "...", "source_type": "web", "confidence": 0.5, "captured_at": null}；不要只返回 URL 字符串。
- 只比较 allowed_products 中的产品。
- 不要编造功能结论；当前采集结果未覆盖该维度时，写“当前采集结果未覆盖，需补充检索”，不要断言公开来源不存在。
输出结构示例：
{"module": "核心能力", "feature_name": "提现手续费", "comparisons": [{"product": "产品名", "support_level": "supported", "difference_summary": "基于来源的比较结论", "evidence_refs": [{"url": "https://example.com", "title": "来源标题", "snippet": "支持结论的来源摘录", "source_type": "web", "confidence": 0.7, "captured_at": null}]}]}
"""

PRICING_SYSTEM_PROMPT = """你是资深竞品分析师。请只基于公开来源输出 PricingComparison JSON。
要求：
- 只返回合法 JSON 对象，不要 Markdown，不要解释。
- tiers[] 必须包含 raw_price、currency、billing_period、pricing_model、highlights、evidence_refs。
- evidence_refs 必须是对象数组，每项格式为 {"url": "...", "title": "...", "snippet": "...", "source_type": "web", "confidence": 0.5, "captured_at": null}；不要只返回 URL 字符串。
- price 必须是数字；无法确认时填 0，并在 raw_price / highlights 中说明未确认。
- 只输出 allowed_products 中的产品。
"""

SENTIMENT_SYSTEM_PROMPT = """你是资深竞品分析师。请只基于公开来源输出 UserSentimentAnalysis JSON。
要求：
- 只返回合法 JSON 对象，不要 Markdown，不要解释。
- per_product 必须覆盖 allowed_products。
- positive / negative / neutral 必须为整数；来源不足时 neutral 至少为 1。
- common_praises / common_complaints 聚合主要共性，不要编造细节。
"""

POSITIONING_SYSTEM_PROMPT = """你是资深竞品分析师。请只基于公开来源输出 PositioningAnalysis JSON。
要求：
- 只返回合法 JSON 对象，不要 Markdown，不要解释。
- 必须覆盖 target_users、scenarios、problems、solutions、rtb 五个维度。
- 每个维度需包含 summary、evidence_refs、confidence。
- evidence_refs 必须是对象数组，每项格式为 {"url": "...", "title": "...", "snippet": "...", "source_type": "web", "confidence": 0.5, "captured_at": null}；不要只返回 URL 字符串。
- 分析重点回答“为谁、在什么场景、解决什么问题、凭什么成立”。
"""

ROLE_SYSTEM_PROMPT = """你是资深竞品分析师。请只基于公开来源输出 CompetitorRoleAnalysis JSON。
要求：
- 只返回合法 JSON 对象，不要 Markdown，不要解释。
- 只针对 competitors 输出 items，不要包含 target_product。
- role 只能是 core、benchmark、potential、substitute、pitfall、unknown。
- 每项都需包含 product、role、reason、evidence_refs、confidence。
- evidence_refs 必须是对象数组，每项格式为 {"url": "...", "title": "...", "snippet": "...", "source_type": "web", "confidence": 0.5, "captured_at": null}；不要只返回 URL 字符串。
- 如果 config.competitor_groups 已给出角色标签，要优先沿用；证据不足时写 unknown。
"""

GTM_SYSTEM_PROMPT = """你是资深竞品分析师。请只基于公开来源输出 GTMAnalysis JSON。
要求：
- 只返回合法 JSON 对象，不要 Markdown，不要解释。
- 必须覆盖 launch_rhythm、budget_allocation、channel_mix、content_strategy、paid_acquisition、business_results。
- 每个维度需包含 summary、evidence_refs、confidence。
- evidence_refs 必须是对象数组，每项格式为 {"url": "...", "title": "...", "snippet": "...", "source_type": "web", "confidence": 0.5, "captured_at": null}；不要只返回 URL 字符串。
- 重点回答上市节奏、渠道组合、内容打法、投放动作和商业结果。
"""


# 手写 JSON schema 嵌入 system prompt 是临时方案。
# 迁移到 with_structured_output / function calling 后，schema 由 Pydantic model
# 自动生成，这段手写 schema 文本即可删除。
ANALYSIS_SYSTEM_PROMPT = """你是资深竞品分析师。请只基于用户提供的搜索来源上下文生成结构化竞品分析 artifact。
要求：
- 只输出一个合法 JSON 对象，不要 Markdown，不要解释。
- 不要编造具体价格、功能或评价；当前采集结果未覆盖时写"当前采集结果未覆盖，需补充检索"或"未在来源中确认"，不要断言公开来源不存在。
- 分析不能停留在“别人做了什么”，要尽量回答其产品定位是否成立、为什么成功或失败，以及这对当前项目有什么参考价值。
- 所有 evidence_refs 都必须是对象数组，每项使用统一结构：url、title、snippet、source_type、confidence、captured_at；不要只返回 URL 字符串。
- feature_matrix.dimensions 应覆盖用户关注维度，matrix 中每项 products 只能包含 allowed_products 中列出的产品。
- feature_matrix.matrix[].comparisons[] 必须包含 product、support_level、difference_summary、evidence_refs。
- 不要新增 allowed_products 之外的产品或竞品列。
- competitor_role_analysis 必须只针对 allowed_products 中除目标产品外的竞品输出；role 只能是 core、benchmark、potential、substitute、pitfall、unknown 之一，并带 reason、evidence_refs、confidence。
- 如果 config.competitor_groups 已经给出角色标签，要优先沿用；如果来源或上下文不足以确认，只能写 unknown，不要硬判。
- pricing_comparison.plans[].tiers[] 必须包含 raw_price、currency、billing_period、pricing_model、evidence_refs；price 必须是数字，无法确认时填 0。
- positioning_analysis 需要覆盖 target_users、scenarios、problems、solutions、rtb 五个维度。
- gtm_analysis 需要覆盖 launch_rhythm、budget_allocation、channel_mix、content_strategy、paid_acquisition、business_results 六个维度。
- user_sentiment.per_product 的 positive/negative/neutral 用整数估计来源倾向，来源不足时 neutral 至少为 1。
- swot.source_refs 使用要点到 URL 列表的映射。
JSON schema:
{
  "feature_matrix": {"dimensions": ["..."], "matrix": [{"module": "...", "feature_name": "...", "comparisons": [{"product": "...", "support_level": "supported", "difference_summary": "...", "evidence_refs": []}], "products": {"产品名": "结论"}}]},
  "pricing_comparison": {"plans": [{"product": "...", "tiers": [{"name": "...", "price": 0, "raw_price": "...", "currency": "...", "billing_period": "...", "pricing_model": "...", "highlights": ["..."], "evidence_refs": []}]}], "summary": "..."},
  "user_sentiment": {"per_product": {"产品名": {"positive": 0, "negative": 0, "neutral": 1}}, "common_praises": ["..."], "common_complaints": ["..."]},
  "positioning_analysis": {"target_users": {"summary": "...", "evidence_refs": [], "confidence": 0.5}, "scenarios": {"summary": "...", "evidence_refs": [], "confidence": 0.5}, "problems": {"summary": "...", "evidence_refs": [], "confidence": 0.5}, "solutions": {"summary": "...", "evidence_refs": [], "confidence": 0.5}, "rtb": {"summary": "...", "evidence_refs": [], "confidence": 0.5}, "summary": "..."},
  "swot": {"product": "目标产品", "strengths": ["..."], "weaknesses": ["..."], "opportunities": ["..."], "threats": ["..."], "source_refs": {"要点": ["url"]}},
  "competitor_role_analysis": {"items": [{"product": "竞品名", "role": "benchmark", "reason": "...", "evidence_refs": [], "confidence": 0.5}], "summary": "..."},
  "gtm_analysis": {"launch_rhythm": {"summary": "...", "evidence_refs": [], "confidence": 0.5}, "budget_allocation": {"summary": "...", "evidence_refs": [], "confidence": 0.5}, "channel_mix": {"summary": "...", "evidence_refs": [], "confidence": 0.5}, "content_strategy": {"summary": "...", "evidence_refs": [], "confidence": 0.5}, "paid_acquisition": {"summary": "...", "evidence_refs": [], "confidence": 0.5}, "business_results": {"summary": "...", "evidence_refs": [], "confidence": 0.5}, "summary": "..."}
}"""


class AnalysisAgent(BaseAgent):
    node_name = "analysis"
    SUBNODE_ARTIFACT_MAP = {
        "feature_analysis": {"feature_matrix"},
        "pricing_analysis": {"pricing_comparison"},
        "sentiment_analysis": {"user_sentiment"},
        "positioning_analysis": {"positioning_analysis"},
        "role_analysis": {"competitor_role_analysis"},
        "gtm_analysis": {"gtm_analysis"},
    }

    async def run(self, state: dict, ctx: AgentContext) -> dict:
        if ctx.node_id != self.node_name and not state.get("__subnode_delegate__"):
            return await self._run_subnode(state, ctx)

        config, target, competitors, competitor_groups, focus_dimensions, raw_data, products = self._analysis_inputs(state)

        await self.log_and_broadcast(ctx, EventType.NODE_START, {
            "input_summary": {
                "phase": "analyzing",
                "target_product": target,
                "products_count": len(products),
                "source_count": sum(len(items) for items in raw_data.values()) if isinstance(raw_data, dict) else 0,
            },
        })
        await self.emit_progress(
            ctx,
            stage="prepare_context",
            message="正在整理采集来源并建立比较上下文，为后续分析准备统一基线。",
        )

        start = time.time()
        previous_outputs = self._existing_outputs(state)

        if llm_is_configured() and raw_data:
            await self.emit_progress(
                ctx,
                stage="run_analysis",
                message="正在生成 SWOT 骨架，后续子节点会继续补齐功能、定价、反馈、定位与增长 artifact。",
            )
            swot = await self.invoke_llm(
                SWOT_SYSTEM_PROMPT,
                self._llm_payload(
                    config=config,
                    target=target,
                    competitors=competitors,
                    competitor_groups=competitor_groups,
                    focus_dimensions=focus_dimensions,
                    raw_data=raw_data,
                    products=products,
                ),
                SWOTAnalysis,
                ctx,
                "analysis_swot",
                request_meta={"products": products},
            )
            await self.log_and_broadcast(ctx, EventType.LLM_RESPONSE, {
                "model_task": "analysis_swot",
                "strengths_count": len(swot.strengths),
            })
            await self.emit_progress(
                ctx,
                stage="swot_ready",
                message="SWOT 已生成，后续分析子节点将独立补齐各自 artifact。",
                level="success",
            )
        else:
            await self.emit_progress(
                ctx,
                stage="fallback_analysis",
                message="未使用实时模型分析，当前将根据现有来源生成 SWOT 草稿，其余 artifact 由子节点逐步补齐。",
                level="warning",
            )
            _, _, _, _, swot, _, _ = self._fallback_analysis(
                target, competitors, focus_dimensions, raw_data, competitor_groups
            )

        merged_outputs = self._merge_outputs(previous_outputs, {"swot": swot.model_dump(mode="json")}, {"swot"})
        duration_ms = int((time.time() - start) * 1000)
        await self.emit_progress(
            ctx,
            stage="analysis_complete",
            message="分析编排节点已完成，后续将进入各个分析子节点。",
            level="success",
        )

        await self.log_and_broadcast(ctx, EventType.NODE_COMPLETE, {
            "output_summary": {
                "swot_strengths": len(SWOTAnalysis.model_validate(merged_outputs["swot"]).strengths),
                "products_count": len(products),
            },
            "duration_ms": duration_ms,
        })

        return {
            **merged_outputs,
            "analysis_modules": self._build_analysis_modules(merged_outputs),
            "current_phase": "analyzing",
        }

    async def _run_subnode(self, state: dict, ctx: AgentContext) -> dict:
        requested_artifacts = self.SUBNODE_ARTIFACT_MAP.get(ctx.node_id, set())
        if not requested_artifacts:
            return {
                "analysis_modules": self._build_analysis_modules(self._existing_outputs(state)),
                "current_phase": "analyzing",
            }

        if not self._should_rerun_subnode(state, ctx.node_id, requested_artifacts):
            await self.log_and_broadcast(ctx, EventType.NODE_START, {
                "input_summary": {
                    "phase": "analyzing",
                    "node": ctx.node_id,
                    "artifacts": list(requested_artifacts),
                },
            })
            outputs = self._existing_outputs(state)
            await self.emit_progress(
                ctx,
                stage="reuse_existing_artifact",
                message=f"{ctx.node_id} 复用已有分析结果，准备进入下一节点。",
                level="success",
            )
            await self.log_and_broadcast(ctx, EventType.NODE_COMPLETE, {
                "output_summary": {"reused": True, "artifacts": list(requested_artifacts)},
                "duration_ms": 0,
            })
            return {
                **outputs,
                "analysis_modules": self._build_analysis_modules(outputs),
                "current_phase": "analyzing",
            }

        subnode_state = dict(state)
        subnode_review = dict(state.get("review_result") or {})
        subnode_review["affected_artifacts"] = list(requested_artifacts)
        subnode_state["review_result"] = subnode_review
        result = await self._generate_subnode_artifact({**subnode_state, "__subnode_delegate__": True}, ctx)
        return result

    async def _generate_subnode_artifact(self, state: dict, ctx: AgentContext) -> dict:
        config, target, competitors, competitor_groups, focus_dimensions, raw_data, products = self._analysis_inputs(state)
        previous_outputs = self._existing_outputs(state)
        artifact_key = next(iter(self.SUBNODE_ARTIFACT_MAP[ctx.node_id]))

        await self.log_and_broadcast(ctx, EventType.NODE_START, {
            "input_summary": {
                "phase": "analyzing",
                "target_product": target,
                "node": ctx.node_id,
                "products_count": len(products),
                "source_count": sum(len(items) for items in raw_data.values()) if isinstance(raw_data, dict) else 0,
            },
        })
        await self.emit_progress(
            ctx,
            stage="prepare_subnode",
            message=f"正在为 {ctx.node_id} 生成独立的结构化 artifact。",
        )

        start = time.time()
        if llm_is_configured() and raw_data:
            payload = self._llm_payload(
                config=config,
                target=target,
                competitors=competitors,
                competitor_groups=competitor_groups,
                focus_dimensions=focus_dimensions,
                raw_data=raw_data,
                products=products,
            )
            generated = await self._invoke_subnode_llm(ctx, payload, products, competitors, competitor_groups)
        else:
            generated = self._fallback_artifact(artifact_key, target, competitors, focus_dimensions, raw_data, competitor_groups)

        merged_outputs = self._merge_outputs(previous_outputs, {artifact_key: generated}, {artifact_key})
        duration_ms = int((time.time() - start) * 1000)
        await self.emit_progress(
            ctx,
            stage="subnode_complete",
            message=f"{ctx.node_id} 已完成，artifact 可用于后续报告与 review。",
            level="success",
        )
        await self.log_and_broadcast(ctx, EventType.NODE_COMPLETE, {
            "output_summary": {"artifact": artifact_key},
            "duration_ms": duration_ms,
        })
        return {
            **merged_outputs,
            "analysis_modules": self._build_analysis_modules(merged_outputs),
            "current_phase": "analyzing",
        }

    def _should_rerun_subnode(self, state: dict, node_id: str, requested_artifacts: set[str]) -> bool:
        existing_outputs = self._existing_outputs(state)
        if any(existing_outputs.get(artifact_key) in (None, {}, []) for artifact_key in requested_artifacts):
            return True

        review = state.get("review_result") or {}
        if not isinstance(review, dict):
            return False

        if review.get("target_node") == node_id:
            return True
        if review.get("retry_scope") == node_id:
            return True

        affected = review.get("affected_artifacts") or []
        if isinstance(affected, list) and requested_artifacts.intersection({
            item for item in affected if isinstance(item, str)
        }):
            return True
        return False

    def _requested_artifacts(self, state: dict) -> set[str]:
        if state.get("__subnode_delegate__"):
            review = state.get("review_result") or {}
            affected = review.get("affected_artifacts") if isinstance(review, dict) else None
            if isinstance(affected, list) and affected:
                return {
                    item for item in affected
                    if item in {
                        "feature_matrix",
                        "pricing_comparison",
                        "user_sentiment",
                        "positioning_analysis",
                        "swot",
                        "competitor_role_analysis",
                        "gtm_analysis",
                    }
                }
        review = state.get("review_result") or {}
        affected = review.get("affected_artifacts") if isinstance(review, dict) else None
        if isinstance(affected, list) and affected:
            return {
                item for item in affected
                if item in {
                    "feature_matrix",
                    "pricing_comparison",
                    "user_sentiment",
                    "positioning_analysis",
                    "swot",
                    "competitor_role_analysis",
                    "gtm_analysis",
                }
            }
        return {
            "feature_matrix",
            "pricing_comparison",
            "user_sentiment",
            "positioning_analysis",
            "swot",
            "competitor_role_analysis",
            "gtm_analysis",
        }

    def _analysis_inputs(self, state: dict) -> tuple[dict, str, list[str], dict, list[str], dict, list[str]]:
        config = state.get("config", {})
        if not isinstance(config, dict):
            config = {}
        target = config.get("target_product", "")
        competitors = config.get("competitors", []) or []
        competitor_groups = config.get("competitor_groups", {}) or {}
        focus_dimensions = config.get(
            "focus_dimensions",
            ["目标用户", "使用场景", "核心问题", "解决方案", "支撑点", "用户反馈", "上市与增长"],
        )
        raw_data = state.get("raw_data", {}) or {}
        if isinstance(raw_data, dict):
            collected_products = [product for product, items in raw_data.items() if product and isinstance(items, list)]
            competitors = [product for product in competitors if product in raw_data]
            if target and target not in raw_data:
                collected_products = [target, *collected_products]
            products = [p for p in [target, *competitors] if p and p in collected_products]
        else:
            raw_data = {}
            products = [p for p in [target, *competitors] if p]
        return config, target, competitors, competitor_groups, focus_dimensions, raw_data, products

    def _llm_payload(
        self,
        *,
        config: dict,
        target: str,
        competitors: list[str],
        competitor_groups: dict,
        focus_dimensions: list[str],
        raw_data: dict,
        products: list[str],
    ) -> dict:
        return {
            "target_product": target,
            "competitors": competitors,
            "allowed_products": products,
            "focus_dimensions": focus_dimensions,
            "competitor_groups": competitor_groups,
            "extra_requirements": config.get("extra_requirements", ""),
            "sources_by_product": raw_data_to_context(raw_data),
        }

    async def _invoke_subnode_llm(
        self,
        ctx: AgentContext,
        payload: dict,
        products: list[str],
        competitors: list[str],
        competitor_groups: dict,
    ) -> dict:
        node_id = ctx.node_id
        if node_id == "feature_analysis":
            return await self._invoke_feature_matrix_by_dimension(ctx, payload, products)
        if node_id == "pricing_analysis":
            result = await self.invoke_llm(PRICING_SYSTEM_PROMPT, payload, PricingComparison, ctx, node_id, request_meta={"products": products})
            return self._restrict_pricing_to_products(result, products).model_dump(mode="json")
        if node_id == "sentiment_analysis":
            result = await self.invoke_llm(SENTIMENT_SYSTEM_PROMPT, payload, UserSentimentAnalysis, ctx, node_id, request_meta={"products": products})
            return self._restrict_sentiment_to_products(result, products).model_dump(mode="json")
        if node_id == "positioning_analysis":
            result = await self.invoke_llm(POSITIONING_SYSTEM_PROMPT, payload, PositioningAnalysis, ctx, node_id, request_meta={"products": products})
            return result.model_dump(mode="json")
        if node_id == "role_analysis":
            result = await self.invoke_llm(ROLE_SYSTEM_PROMPT, payload, CompetitorRoleAnalysis, ctx, node_id, request_meta={"products": competitors})
            return self._restrict_role_analysis(result, competitors, competitor_groups).model_dump(mode="json")
        if node_id == "gtm_analysis":
            try:
                result = await self.invoke_llm(GTM_SYSTEM_PROMPT, payload, GTMAnalysis, ctx, node_id, request_meta={"products": products})
                return result.model_dump(mode="json")
            except Exception as exc:
                await self.emit_progress(
                    ctx,
                    stage="gtm_analysis_fallback",
                    message=f"GTM 模型分析失败，已使用现有来源生成方向性结果：{str(exc)[:160]}",
                    level="warning",
                )
                return self._fallback_artifact(
                    "gtm_analysis",
                    str(payload.get("target_product") or ""),
                    competitors,
                    self._feature_dimensions(payload.get("focus_dimensions")),
                    payload.get("sources_by_product") if isinstance(payload.get("sources_by_product"), dict) else {},
                    competitor_groups,
                )
        raise ValueError(f"Unsupported analysis subnode: {node_id}")

    async def _invoke_feature_matrix_by_dimension(
        self,
        ctx: AgentContext,
        payload: dict,
        products: list[str],
    ) -> dict:
        """Generate one compact FeatureItem per dimension and merge them locally."""
        dimensions = self._feature_dimensions(payload.get("focus_dimensions"))
        matrix: list[FeatureItem] = []

        for index, dimension in enumerate(dimensions, start=1):
            await self.emit_progress(
                ctx,
                stage="analyze_feature_dimension",
                message=f"正在分析功能维度 {index}/{len(dimensions)}：{dimension}",
            )
            dimension_payload = {
                **payload,
                "requested_dimension": dimension,
                "focus_dimensions": [dimension],
                "sources_by_product": self._sources_for_feature_dimension(
                    payload.get("sources_by_product"),
                    dimension,
                ),
            }

            try:
                item = await self.invoke_llm(
                    FEATURE_SYSTEM_PROMPT,
                    dimension_payload,
                    FeatureItem,
                    ctx,
                    f"feature_analysis:{index}",
                    request_meta={
                        "products": products,
                        "dimension": dimension,
                        "dimension_index": index,
                        "dimension_total": len(dimensions),
                    },
                )
                item = self._normalize_feature_item(item, dimension, products)
                if not self._feature_item_is_deliverable(item):
                    raise ValueError("FeatureItem contains no evidence-backed resolved comparison")
            except Exception as exc:
                item = self._fallback_feature_item(
                    dimension,
                    products,
                    dimension_payload["sources_by_product"],
                )
                await self.emit_progress(
                    ctx,
                    stage="feature_dimension_fallback",
                    message=f"{dimension} 的模型分析失败，已保留来源并生成待复核占位：{str(exc)[:160]}",
                    level="warning",
                )
            else:
                await self.emit_progress(
                    ctx,
                    stage="feature_dimension_complete",
                    message=f"{dimension} 已完成。",
                    level="success",
                )
            matrix.append(item)

        return self._without_all_unknown_dimensions(
            FeatureMatrix(dimensions=dimensions, matrix=matrix)
        ).model_dump(mode="json")

    @staticmethod
    def _feature_dimensions(raw_dimensions) -> list[str]:
        dimensions = raw_dimensions if isinstance(raw_dimensions, list) else []
        normalized: list[str] = []
        for dimension in dimensions:
            value = str(dimension).strip()
            if value and value not in normalized:
                normalized.append(value)
        return normalized or ["功能", "定价", "用户评价", "市场定位"]

    @staticmethod
    def _sources_for_feature_dimension(sources_by_product, dimension: str) -> dict[str, list[dict]]:
        """Keep dimension-matched evidence plus a small general-evidence fallback."""
        if not isinstance(sources_by_product, dict):
            return {}
        dimension_intent = f"dimension:{dimension}"
        selected_by_product: dict[str, list[dict]] = {}
        for product, raw_items in sources_by_product.items():
            items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
            matched = [
                item for item in items
                if dimension_intent in (item.get("source_intents") or [item.get("source_intent")])
            ]
            if len(matched) < 3:
                matched_urls = {item.get("url") for item in matched}
                matched.extend(
                    item for item in items
                    if item.get("url") not in matched_urls
                    and (
                        item.get("source_intent") in {"official", "independent_evidence", "overview"}
                        or any(
                            intent in {"official", "independent_evidence", "overview"}
                            for intent in (item.get("source_intents") or [])
                        )
                    )
                )
            selected_by_product[str(product)] = matched[:4]
        return selected_by_product

    @staticmethod
    def _normalize_feature_item(item: FeatureItem, dimension: str, products: list[str]) -> FeatureItem:
        data = item.model_dump(mode="json")
        allowed = set(products)
        data["feature_name"] = dimension
        data["comparisons"] = [
            comparison for comparison in data.get("comparisons", [])
            if comparison.get("product") in allowed
        ]
        products_map = data.get("products") or {}
        data["products"] = {
            product: summary for product, summary in products_map.items()
            if product in allowed
        }
        return FeatureItem.model_validate(data)

    @staticmethod
    def _feature_item_is_deliverable(item: FeatureItem) -> bool:
        return AnalysisAgent._feature_matrix_is_deliverable(
            FeatureMatrix(dimensions=[item.feature_name], matrix=[item])
        )

    @staticmethod
    def _without_all_unknown_dimensions(feature_matrix: FeatureMatrix) -> FeatureMatrix:
        """Hide dimensions that have no resolved product comparison."""
        visible_items = [
            item for item in feature_matrix.matrix
            if any(
                comparison.support_level.strip().lower() not in {"", "unknown", "未确认"}
                for comparison in item.comparisons
            )
        ]
        visible_names = {item.feature_name for item in visible_items}
        return FeatureMatrix(
            dimensions=[
                dimension for dimension in feature_matrix.dimensions
                if dimension in visible_names
            ],
            matrix=visible_items,
        )

    @staticmethod
    def _fallback_feature_item(
        dimension: str,
        products: list[str],
        sources_by_product: dict[str, list[dict]],
    ) -> FeatureItem:
        comparisons = []
        for product in products:
            sources = sources_by_product.get(product, []) if isinstance(sources_by_product, dict) else []
            refs = [
                {
                    "url": source.get("url", ""),
                    "title": source.get("title", "") or source.get("url", ""),
                    "snippet": source.get("snippet", ""),
                    "source_type": "search_result",
                    "confidence": 0.4,
                }
                for source in sources[:2]
                if isinstance(source, dict) and source.get("url")
            ]
            comparisons.append(FeatureComparison(
                product=product,
                support_level="unknown",
                difference_summary="该维度模型分析未成功完成，已保留相关来源，需后续复核。",
                evidence_refs=refs,
            ))
        return FeatureItem(
            module="核心能力",
            feature_name=dimension,
            comparisons=comparisons,
        )

    def _fallback_artifact(
        self,
        artifact_key: str,
        target: str,
        competitors: list[str],
        focus_dimensions: list[str],
        raw_data: dict,
        competitor_groups: dict,
    ) -> dict:
        feature_matrix, pricing_comparison, user_sentiment, positioning_analysis, swot, competitor_role_analysis, gtm_analysis = self._fallback_analysis(
            target, competitors, focus_dimensions, raw_data, competitor_groups
        )
        fallback_outputs = {
            "feature_matrix": feature_matrix.model_dump(mode="json"),
            "pricing_comparison": pricing_comparison.model_dump(mode="json"),
            "user_sentiment": user_sentiment.model_dump(mode="json"),
            "positioning_analysis": positioning_analysis.model_dump(mode="json"),
            "swot": swot.model_dump(mode="json"),
            "competitor_role_analysis": competitor_role_analysis.model_dump(mode="json"),
            "gtm_analysis": gtm_analysis.model_dump(mode="json"),
        }
        return fallback_outputs[artifact_key]

    def _existing_outputs(self, state: dict) -> dict:
        return {
            "feature_matrix": state.get("feature_matrix"),
            "pricing_comparison": state.get("pricing_comparison"),
            "user_sentiment": state.get("user_sentiment"),
            "positioning_analysis": state.get("positioning_analysis"),
            "swot": state.get("swot"),
            "competitor_role_analysis": state.get("competitor_role_analysis"),
            "gtm_analysis": state.get("gtm_analysis"),
        }

    def _merge_outputs(self, previous_outputs: dict, fresh_outputs: dict, requested_artifacts: set[str]) -> dict:
        merged = dict(previous_outputs)
        for key, value in fresh_outputs.items():
            if key in requested_artifacts or previous_outputs.get(key) in (None, {}, []):
                merged[key] = value
        return merged

    def _build_analysis_modules(self, outputs: dict) -> dict:
        return {
            "feature_analysis": {"artifact": "feature_matrix", "complete": bool((outputs.get("feature_matrix") or {}).get("matrix"))},
            "pricing_analysis": {"artifact": "pricing_comparison", "complete": bool((outputs.get("pricing_comparison") or {}).get("plans"))},
            "sentiment_analysis": {"artifact": "user_sentiment", "complete": bool((outputs.get("user_sentiment") or {}).get("per_product"))},
            "positioning_analysis": {"artifact": "positioning_analysis", "complete": bool((outputs.get("positioning_analysis") or {}).get("summary"))},
            "role_analysis": {"artifact": "competitor_role_analysis", "complete": bool((outputs.get("competitor_role_analysis") or {}).get("items"))},
            "gtm_analysis": {"artifact": "gtm_analysis", "complete": bool((outputs.get("gtm_analysis") or {}).get("summary"))},
        }

    def _restrict_to_products(
        self,
        feature_matrix: FeatureMatrix,
        pricing_comparison: PricingComparison,
        user_sentiment: UserSentimentAnalysis,
        allowed_products: list[str],
    ) -> tuple[FeatureMatrix, PricingComparison, UserSentimentAnalysis]:
        allowed = set(allowed_products)

        feature_data = feature_matrix.model_dump(mode="json")
        for item in feature_data.get("matrix", []):
            products = item.get("products", {})
            if isinstance(products, dict):
                item["products"] = {name: value for name, value in products.items() if name in allowed}

        pricing_data = pricing_comparison.model_dump(mode="json")
        pricing_data["plans"] = [
            plan for plan in pricing_data.get("plans", [])
            if plan.get("product") in allowed
        ]

        sentiment_data = user_sentiment.model_dump(mode="json")
        per_product = sentiment_data.get("per_product", {})
        if isinstance(per_product, dict):
            sentiment_data["per_product"] = {
                name: value for name, value in per_product.items() if name in allowed
            }

        return (
            FeatureMatrix.model_validate(feature_data),
            PricingComparison.model_validate(pricing_data),
            UserSentimentAnalysis.model_validate(sentiment_data),
        )

    @staticmethod
    def _feature_matrix_is_deliverable(feature_matrix: FeatureMatrix) -> bool:
        """Reject schema-valid matrices that contain only placeholders."""
        placeholder_markers = (
            "当前采集结果未覆盖",
            "需补充检索",
            "尚待分析",
            "需要进一步分析",
            "未确认",
        )
        for row in feature_matrix.matrix:
            for comparison in row.comparisons:
                summary = comparison.difference_summary.strip()
                has_resolved_level = comparison.support_level.strip().lower() not in {"", "unknown", "未确认"}
                has_meaningful_summary = len(summary) >= 12 and not any(
                    marker in summary for marker in placeholder_markers
                )
                has_evidence_content = any(
                    ref.url.strip()
                    for ref in comparison.evidence_refs
                )
                if has_resolved_level and has_meaningful_summary and has_evidence_content:
                    return True
        return False

    def _restrict_pricing_to_products(self, pricing_comparison: PricingComparison, allowed_products: list[str]) -> PricingComparison:
        pricing_data = pricing_comparison.model_dump(mode="json")
        allowed = set(allowed_products)
        pricing_data["plans"] = [
            plan for plan in pricing_data.get("plans", [])
            if plan.get("product") in allowed
        ]
        return PricingComparison.model_validate(pricing_data)

    def _restrict_sentiment_to_products(self, user_sentiment: UserSentimentAnalysis, allowed_products: list[str]) -> UserSentimentAnalysis:
        sentiment_data = user_sentiment.model_dump(mode="json")
        allowed = set(allowed_products)
        per_product = sentiment_data.get("per_product", {})
        if isinstance(per_product, dict):
            sentiment_data["per_product"] = {
                name: value for name, value in per_product.items() if name in allowed
            }
        return UserSentimentAnalysis.model_validate(sentiment_data)

    def _restrict_role_analysis(
        self,
        role_analysis: CompetitorRoleAnalysis,
        competitors: list[str],
        configured_groups: dict,
    ) -> CompetitorRoleAnalysis:
        allowed = set(competitors)
        configured_roles = self._configured_role_map(configured_groups)
        items = []
        seen: set[str] = set()
        for item in role_analysis.items:
            if item.product not in allowed or item.product in seen:
                continue
            seen.add(item.product)
            role = configured_roles.get(item.product, item.role or "unknown")
            items.append(CompetitorRoleItem(
                product=item.product,
                role=role,
                reason=item.reason,
                evidence_refs=item.evidence_refs,
                confidence=item.confidence,
            ))
        for product in competitors:
            if product in seen:
                continue
            items.append(CompetitorRoleItem(
                product=product,
                role=configured_roles.get(product, "unknown"),
                reason="当前基于用户选择的竞品范围进行分析，角色判断仍需结合细分市场上下文进一步确认。"
                if product not in configured_roles else "沿用访谈阶段已确认的竞品角色判断。",
                evidence_refs=[],
                confidence=0.4,
            ))
        summary = role_analysis.summary if role_analysis.summary else self._build_role_summary(items)
        return CompetitorRoleAnalysis(items=items, summary=summary)

    def _fallback_analysis(
        self,
        target: str,
        competitors: list[str],
        focus_dimensions: list[str],
        raw_data: dict,
        competitor_groups: dict,
    ) -> tuple[FeatureMatrix, PricingComparison, UserSentimentAnalysis, PositioningAnalysis, SWOTAnalysis, CompetitorRoleAnalysis, GTMAnalysis]:
        products = [p for p in [target, *competitors] if p]
        if not products:
            products = ["目标产品"]

        matrix = []
        for dimension in focus_dimensions or ["功能", "定价", "用户评价", "市场定位"]:
            comparisons = [
                {
                    "product": product,
                    "support_level": "unknown",
                    "difference_summary": self._source_based_summary(product, raw_data.get(product, [])),
                    "evidence_refs": [ref.model_dump(mode="json") for ref in self._evidence_refs(product, raw_data)],
                }
                for product in products
            ]
            matrix.append({
                "module": "核心能力",
                "feature_name": dimension,
                "comparisons": comparisons,
                "products": {
                    product: self._source_based_summary(product, raw_data.get(product, []))
                    for product in products
                },
            })

        pricing_plans = []
        for product in products:
            pricing_plans.append({
                "product": product,
                "tiers": [{
                    "name": "公开信息",
                    "price": 0.0,
                    "raw_price": "未确认",
                    "currency": "",
                    "billing_period": "",
                    "pricing_model": "unknown",
                    "highlights": ["未配置 LLM 或来源不足，无法确认具体价格"],
                    "evidence_refs": [ref.model_dump(mode="json") for ref in self._evidence_refs(product, raw_data)],
                }],
            })

        # neutral 至少为 1，避免 sentiment 全零导致下游消费者误判"无数据"
        per_product = {
            product: {"positive": 0, "negative": 0, "neutral": max(1, len(raw_data.get(product, [])))}
            for product in products
        }
        source_refs = {
            "公开来源": [
                item.get("url", "")
                for items in raw_data.values()
                for item in items[:2]
                if isinstance(item, dict) and item.get("url")
            ][:8]
        }
        positioning = PositioningAnalysis(
            target_users=PositioningDimension(
                summary=f"{target or products[0]} 当前主要面向的目标用户仍需结合更多公开来源确认。",
                evidence_refs=self._evidence_refs(target or products[0], raw_data),
                confidence=0.45,
            ),
            scenarios=PositioningDimension(
                summary="现阶段只能从公开来源粗略判断其使用场景，具体高频场景仍需更多证据。",
                evidence_refs=self._evidence_refs(target or products[0], raw_data),
                confidence=0.4,
            ),
            problems=PositioningDimension(
                summary="当前只能确认其试图解决相关产品效率或体验问题，但尚未形成稳定判断。",
                evidence_refs=self._evidence_refs(target or products[0], raw_data),
                confidence=0.4,
            ),
            solutions=PositioningDimension(
                summary="解决方案判断暂基于有限来源，建议后续结合产品截图与流程进一步确认。",
                evidence_refs=self._evidence_refs(target or products[0], raw_data),
                confidence=0.45,
            ),
            rtb=PositioningDimension(
                summary="当前 Reason to Believe 仍偏弱，建议后续补充技术、口碑和品牌势能证据。",
                evidence_refs=self._evidence_refs(target or products[0], raw_data),
                confidence=0.35,
            ),
            summary="当前已形成定位分析骨架，但仍需更多证据支持用户、场景、问题、方案与支撑点的完整判断。",
        )
        gtm = GTMAnalysis(
            launch_rhythm=GTMSection(summary="当前采集结果未覆盖，暂无法确认其上市节奏。"),
            budget_allocation=GTMSection(summary="当前采集结果未覆盖，暂无法确认其预算结构。"),
            channel_mix=GTMSection(summary="当前只能识别零散渠道线索，尚未形成完整平台组合判断。"),
            content_strategy=GTMSection(summary="可初步关注其价值主张表达，但当前仍缺少足够内容证据。"),
            paid_acquisition=GTMSection(summary="未在有限来源中稳定确认其投放动作。"),
            business_results=GTMSection(summary="当前缺少可靠商业结果证据。"),
            summary="上市与增长分析目前仍属于方向性判断，后续需要更系统的内容、渠道与结果证据。",
        )

        return (
            FeatureMatrix.model_validate({"dimensions": focus_dimensions, "matrix": matrix}),
            PricingComparison.model_validate({
                "plans": pricing_plans,
                "summary": "当前未配置可用 LLM，或采集来源不足；定价结论需要在接入真实模型和搜索结果后复核。",
            }),
            UserSentimentAnalysis.model_validate({
                "per_product": per_product,
                "common_praises": ["需要更多用户评价来源后提炼"],
                "common_complaints": ["需要更多用户评价来源后提炼"],
            }),
            positioning,
            SWOTAnalysis(
                product=target or products[0],
                strengths=["已建立竞品分析工作流，可在接入真实来源后自动生成结论"],
                weaknesses=["当前分析基于有限来源，具体业务结论可信度有限"],
                opportunities=["补充真实搜索和 LLM 配置后，可提升分析覆盖度和自动化程度"],
                threats=["来源不足或模型输出不稳定会影响结论质量"],
                source_refs=source_refs,
            ),
            self._fallback_role_analysis(competitors, competitor_groups),
            gtm,
        )

    def _source_based_summary(self, product: str, sources: list) -> str:
        """Use source excerpts for an explicitly provisional fallback summary."""
        if not sources:
            return "当前采集结果未覆盖，需补充检索"
        excerpts = [
            str(item.get("snippet") or item.get("content_summary") or item.get("content") or "").strip()
            for item in sources[:2]
            if isinstance(item, dict)
        ]
        excerpts = [excerpt[:180] for excerpt in excerpts if excerpt]
        if not excerpts:
            return f"已找到 {len(sources)} 条来源，但尚未提取出可用于比较的有效内容"
        return "来源摘录，尚待分析：" + "；".join(excerpts)

    def _configured_role_map(self, groups: dict) -> dict[str, str]:
        if not isinstance(groups, dict):
            return {}
        role_map: dict[str, str] = {}
        for role in ("core", "benchmark", "potential", "substitute", "pitfall"):
            for product in groups.get(role, []) or []:
                if isinstance(product, str) and product:
                    role_map[product] = role
        return role_map

    def _fallback_role_analysis(self, competitors: list[str], competitor_groups: dict) -> CompetitorRoleAnalysis:
        configured_roles = self._configured_role_map(competitor_groups)
        items = [
            CompetitorRoleItem(
                product=product,
                role=configured_roles.get(product, "unknown"),
                reason="当前沿用访谈阶段的竞品选择与角色标签，后续应结合更多来源验证这一判断。"
                if product in configured_roles else
                "当前已纳入分析范围，但角色判断证据不足，建议在后续分析中继续确认其在细分市场中的位置。",
                evidence_refs=[],
                confidence=0.45 if product in configured_roles else 0.35,
            )
            for product in competitors
        ]
        return CompetitorRoleAnalysis(items=items, summary=self._build_role_summary(items))

    def _evidence_refs(self, product: str, raw_data: dict, limit: int = 2) -> list[EvidenceRef]:
        items = raw_data.get(product, []) if isinstance(raw_data, dict) else []
        refs: list[EvidenceRef] = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            refs.append(EvidenceRef(
                url=item.get("url", ""),
                title=item.get("title", "") or item.get("url", ""),
                snippet=str(item.get("snippet") or item.get("content_summary") or item.get("content") or "")[:200],
                source_type="search_result",
                confidence=0.6,
                captured_at=datetime.utcnow(),
            ))
        return refs

    def _build_role_summary(self, items: list[CompetitorRoleItem]) -> str:
        if not items:
            return "当前未形成足够明确的竞品角色判断。"
        labels = {
            "core": "核心竞品",
            "benchmark": "标杆竞品",
            "potential": "潜力竞品",
            "substitute": "替代竞品",
            "pitfall": "避坑竞品",
            "unknown": "待确认角色",
        }
        groups: dict[str, list[str]] = {}
        for item in items:
            groups.setdefault(item.role, []).append(item.product)
        parts = []
        for role, names in groups.items():
            parts.append(f"{labels.get(role, role)}：" + "、".join(names))
        return "；".join(parts)
