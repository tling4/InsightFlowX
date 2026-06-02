import time
import uuid
from app.agents.base_agent import BaseAgent
from app.agents.agent_utils import llm_is_configured, raw_data_to_context
from app.services.event_service import EventLogger
from app.schemas.event import EventType
from app.schemas.feature import FeatureMatrix
from app.schemas.pricing import PricingComparison
from app.schemas.sentiment import UserSentimentAnalysis
from app.schemas.swot import SWOTAnalysis
from pydantic import BaseModel


class AnalysisBundle(BaseModel):
    """LLM 一次调用返回的完整分析产物集合。

    用单个 schema 包裹避免四次独立 LLM 调用，减少延迟和 token 消耗。
    迁移到 function calling 后，可改为四个独立 tool call 在一次请求内并行返回。
    """
    feature_matrix: FeatureMatrix
    pricing_comparison: PricingComparison
    user_sentiment: UserSentimentAnalysis
    swot: SWOTAnalysis


# 手写 JSON schema 嵌入 system prompt 是临时方案。
# 迁移到 with_structured_output / function calling 后，schema 由 Pydantic model
# 自动生成，这段手写 schema 文本即可删除。
ANALYSIS_SYSTEM_PROMPT = """你是资深竞品分析师。请只基于用户提供的搜索来源上下文生成结构化竞品分析。
要求：
- 只输出一个合法 JSON 对象，不要 Markdown，不要解释。
- 不要编造具体价格、功能或评价；来源不足时写"公开来源不足"或"未在来源中确认"。
- feature_matrix.dimensions 应覆盖用户关注维度，matrix 中每项 products 只能包含 allowed_products 中列出的产品。
- 不要新增 allowed_products 之外的产品或竞品列。
- pricing_comparison.plans[].tiers[].price 必须是数字；无法确认具体价格时填 0，并在 highlights 说明未确认。
- user_sentiment.per_product 的 positive/negative/neutral 用整数估计来源倾向，来源不足时 neutral 至少为 1。
- swot.source_refs 使用要点到 URL 列表的映射。
JSON schema:
{
  "feature_matrix": {"dimensions": ["..."], "matrix": [{"feature_name": "...", "products": {"产品名": "结论"}}]},
  "pricing_comparison": {"plans": [{"product": "...", "tiers": [{"name": "...", "price": 0, "highlights": ["..."]}]}], "summary": "..."},
  "user_sentiment": {"per_product": {"产品名": {"positive": 0, "negative": 0, "neutral": 1}}, "common_praises": ["..."], "common_complaints": ["..."]},
  "swot": {"product": "目标产品", "strengths": ["..."], "weaknesses": ["..."], "opportunities": ["..."], "threats": ["..."], "source_refs": {"要点": ["url"]}}
}"""


class AnalysisAgent(BaseAgent):
    node_name = "analysis"

    async def run(self, state: dict, event_logger: EventLogger, workflow_id: uuid.UUID) -> dict:
        """将采集阶段产出的原始搜索结果转为结构化竞品分析。

        LLM 可用时：调用 invoke_llm（流式 + 结构化解码），一次返回四大分析产物。
        LLM 不可用时：走 _fallback_analysis 用规则拼装占位数据，保证工作流不中断。
        """
        config = state.get("config", {})
        if not isinstance(config, dict):
            config = {}
        target = config.get("target_product", "")
        competitors = config.get("competitors", []) or []
        focus_dimensions = config.get("focus_dimensions", ["功能", "定价", "用户评价", "市场定位"])
        raw_data = state.get("raw_data", {}) or {}
        if isinstance(raw_data, dict):
            collected_products = [product for product, items in raw_data.items() if product and isinstance(items, list)]
            competitors = [product for product in competitors if product in raw_data]
            if target and target not in raw_data:
                collected_products = [target, *collected_products]
            products = [p for p in [target, *competitors] if p and p in collected_products]
        else:
            products = [p for p in [target, *competitors] if p]

        await self.log_and_broadcast(event_logger, EventType.NODE_START, {
            "input_summary": {
                "phase": "analyzing",
                "target_product": target,
                "products_count": len(products),
                "source_count": sum(len(items) for items in raw_data.values()) if isinstance(raw_data, dict) else 0,
            },
        }, workflow_id)
        await self.emit_progress(
            event_logger,
            workflow_id,
            stage="prepare_context",
            message="正在整理采集来源并建立比较上下文，为后续分析准备统一基线。",
        )

        start = time.time()

        if llm_is_configured() and raw_data:
            await self.emit_progress(
                event_logger,
                workflow_id,
                stage="run_analysis",
                message="正在比较功能维度、整理定价信息、归纳用户反馈并生成 SWOT 结论。",
            )
            bundle = await self.invoke_llm(
                ANALYSIS_SYSTEM_PROMPT,
                {
                    "target_product": target,
                    "competitors": competitors,
                    "allowed_products": products,
                    "focus_dimensions": focus_dimensions,
                    "extra_requirements": config.get("extra_requirements", ""),
                    "sources_by_product": raw_data_to_context(raw_data),
                },
                AnalysisBundle,
                event_logger, workflow_id, "competitive_analysis",
                request_meta={"products": products},
            )
            # LLM_RESPONSE 仍由 agent 自行记录，携带分析特有的摘要字段
            await self.log_and_broadcast(event_logger, EventType.LLM_RESPONSE, {
                "model_task": "competitive_analysis",
                "feature_items": len(bundle.feature_matrix.matrix),
            }, workflow_id)
            feature_matrix = bundle.feature_matrix
            pricing_comparison = bundle.pricing_comparison
            user_sentiment = bundle.user_sentiment
            swot = bundle.swot
            feature_matrix, pricing_comparison, user_sentiment = self._restrict_to_products(
                feature_matrix,
                pricing_comparison,
                user_sentiment,
                products,
            )
            await self.emit_progress(
                event_logger,
                workflow_id,
                stage="feature_matrix_ready",
                message=f"功能对比已完成，当前覆盖 {len(feature_matrix.dimensions)} 个分析维度。",
                level="success",
            )
            await self.emit_progress(
                event_logger,
                workflow_id,
                stage="pricing_ready",
                message=f"定价信息已整理完成，当前输出 {len(pricing_comparison.plans)} 组产品方案。",
                level="success",
            )
            await self.emit_progress(
                event_logger,
                workflow_id,
                stage="sentiment_ready",
                message=f"用户反馈归纳完成，当前覆盖 {len(user_sentiment.per_product)} 个产品。",
                level="success",
            )
            await self.emit_progress(
                event_logger,
                workflow_id,
                stage="swot_ready",
                message="SWOT 结论已生成，正在汇总结构化分析结果。",
                level="success",
            )
        else:
            await self.emit_progress(
                event_logger,
                workflow_id,
                stage="fallback_analysis",
                message="未使用实时模型分析，当前将根据现有来源生成规则化分析草稿。",
                level="warning",
            )
            feature_matrix, pricing_comparison, user_sentiment, swot = self._fallback_analysis(
                target, competitors, focus_dimensions, raw_data
            )

        duration_ms = int((time.time() - start) * 1000)
        await self.emit_progress(
            event_logger,
            workflow_id,
            stage="analysis_complete",
            message="结构化分析已完成，结果可用于生成竞品分析报告。",
            level="success",
        )

        await self.log_and_broadcast(event_logger, EventType.NODE_COMPLETE, {
            "output_summary": {
                "dimensions_count": len(feature_matrix.dimensions),
                "feature_items": len(feature_matrix.matrix),
                "pricing_plans": len(pricing_comparison.plans),
            },
            "duration_ms": duration_ms,
        }, workflow_id)

        return {
            "feature_matrix": feature_matrix.model_dump(mode="json"),
            "pricing_comparison": pricing_comparison.model_dump(mode="json"),
            "user_sentiment": user_sentiment.model_dump(mode="json"),
            "swot": swot.model_dump(mode="json"),
            "current_phase": "analyzing",
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

    def _fallback_analysis(
        self,
        target: str,
        competitors: list[str],
        focus_dimensions: list[str],
        raw_data: dict,
    ) -> tuple[FeatureMatrix, PricingComparison, UserSentimentAnalysis, SWOTAnalysis]:
        """无 LLM 或无搜索来源时的规则兜底：用搜索结果标题拼装最低限度分析产物。

        触发条件：llm_is_configured() 为 False，或 raw_data 为空。
        产出的内容仅标注来源情况，不做实质性分析结论。
        """
        products = [p for p in [target, *competitors] if p]
        if not products:
            products = ["目标产品"]

        matrix = []
        for dimension in focus_dimensions or ["功能", "定价", "用户评价", "市场定位"]:
            matrix.append({
                "feature_name": dimension,
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
                    "highlights": ["未配置 LLM 或来源不足，无法确认具体价格"],
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
            SWOTAnalysis(
                product=target or products[0],
                strengths=["已建立竞品分析工作流，可在接入真实来源后自动生成结论"],
                weaknesses=["当前分析基于有限来源，具体业务结论可信度有限"],
                opportunities=["补充真实搜索和 LLM 配置后，可提升分析覆盖度和自动化程度"],
                threats=["来源不足或模型输出不稳定会影响结论质量"],
                source_refs=source_refs,
            ),
        )

    def _source_based_summary(self, product: str, sources: list) -> str:
        """用搜索结果标题拼装简短的来源摘要，兜底时替代 LLM 分析结论。"""
        if not sources:
            return "公开来源不足，未确认"
        titles = [item.get("title", "") for item in sources[:2] if isinstance(item, dict)]
        if not titles:
            return f"找到 {len(sources)} 条来源，但需要进一步分析"
        return "；".join(titles)
