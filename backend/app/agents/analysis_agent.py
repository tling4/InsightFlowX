import time
import uuid
from app.agents.base_agent import BaseAgent
from app.agents.agent_utils import invoke_json_model, llm_is_configured, raw_data_to_context
from app.services.event_service import EventLogger
from app.schemas.event import EventType
from app.schemas.feature import FeatureMatrix
from app.schemas.pricing import PricingComparison
from app.schemas.sentiment import UserSentimentAnalysis
from app.schemas.swot import SWOTAnalysis
from pydantic import BaseModel


class AnalysisBundle(BaseModel):
    feature_matrix: FeatureMatrix
    pricing_comparison: PricingComparison
    user_sentiment: UserSentimentAnalysis
    swot: SWOTAnalysis


ANALYSIS_SYSTEM_PROMPT = """你是资深竞品分析师。请只基于用户提供的搜索来源上下文生成结构化竞品分析。
要求：
- 只输出一个合法 JSON 对象，不要 Markdown，不要解释。
- 不要编造具体价格、功能或评价；来源不足时写“公开来源不足”或“未在来源中确认”。
- feature_matrix.dimensions 应覆盖用户关注维度，matrix 中每项 products 要包含目标产品和所有竞品。
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
        """Turn collected raw data into structured competitive analysis."""
        config = state.get("config", {})
        if not isinstance(config, dict):
            config = {}
        target = config.get("target_product", "")
        competitors = config.get("competitors", []) or []
        products = [p for p in [target, *competitors] if p]
        focus_dimensions = config.get("focus_dimensions", ["功能", "定价", "用户评价", "市场定位"])
        raw_data = state.get("raw_data", {}) or {}

        await self.log_and_broadcast(event_logger, EventType.NODE_START, {
            "input_summary": {
                "phase": "analyzing",
                "target_product": target,
                "products_count": len(products),
                "source_count": sum(len(items) for items in raw_data.values()) if isinstance(raw_data, dict) else 0,
            },
        }, workflow_id)

        start = time.time()

        if llm_is_configured() and raw_data:
            await self.log_and_broadcast(event_logger, EventType.LLM_REQUEST, {
                "model_task": "competitive_analysis",
                "products": products,
            }, workflow_id)
            bundle = await invoke_json_model(
                ANALYSIS_SYSTEM_PROMPT,
                {
                    "target_product": target,
                    "competitors": competitors,
                    "focus_dimensions": focus_dimensions,
                    "extra_requirements": config.get("extra_requirements", ""),
                    "sources_by_product": raw_data_to_context(raw_data),
                },
                AnalysisBundle,
            )
            await self.log_and_broadcast(event_logger, EventType.LLM_RESPONSE, {
                "model_task": "competitive_analysis",
                "feature_items": len(bundle.feature_matrix.matrix),
            }, workflow_id)
            feature_matrix = bundle.feature_matrix
            pricing_comparison = bundle.pricing_comparison
            user_sentiment = bundle.user_sentiment
            swot = bundle.swot
        else:
            feature_matrix, pricing_comparison, user_sentiment, swot = self._fallback_analysis(
                target, competitors, focus_dimensions, raw_data
            )

        duration_ms = int((time.time() - start) * 1000)

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

    def _fallback_analysis(
        self,
        target: str,
        competitors: list[str],
        focus_dimensions: list[str],
        raw_data: dict,
    ) -> tuple[FeatureMatrix, PricingComparison, UserSentimentAnalysis, SWOTAnalysis]:
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
        if not sources:
            return "公开来源不足，未确认"
        titles = [item.get("title", "") for item in sources[:2] if isinstance(item, dict)]
        if not titles:
            return f"找到 {len(sources)} 条来源，但需要进一步分析"
        return "；".join(titles)
