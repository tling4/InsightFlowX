import time
import uuid
from app.agents.base_agent import BaseAgent
from app.services.event_service import EventLogger
from app.schemas.event import EventType
from app.schemas.feature import FeatureMatrix
from app.schemas.pricing import PricingComparison
from app.schemas.sentiment import UserSentimentAnalysis
from app.schemas.swot import SWOTAnalysis


class AnalysisAgent(BaseAgent):
    node_name = "analysis"

    async def run(self, state: dict, event_logger: EventLogger, workflow_id: uuid.UUID) -> dict:
        """Stub：记录事件，返回空分析结果。"""
        config = state.get("config", {})
        target = config.get("target_product", "") if isinstance(config, dict) else ""

        await self.log_and_broadcast(event_logger, EventType.NODE_START, {
            "input_summary": {"phase": "analyzing", "target_product": target},
        }, workflow_id)

        start = time.time()

        feature_matrix = FeatureMatrix(dimensions=[], matrix=[])
        pricing_comparison = PricingComparison(plans=[], summary="")
        user_sentiment = UserSentimentAnalysis(per_product={}, common_praises=[], common_complaints=[])
        swot = SWOTAnalysis(
            product=target,
            strengths=[], weaknesses=[], opportunities=[], threats=[],
            source_refs={},
        )

        duration_ms = int((time.time() - start) * 1000)

        await self.log_and_broadcast(event_logger, EventType.NODE_COMPLETE, {
            "output_summary": {"dimensions_count": 0},
            "duration_ms": duration_ms,
        }, workflow_id)

        return {
            "feature_matrix": feature_matrix.model_dump(mode="json"),
            "pricing_comparison": pricing_comparison.model_dump(mode="json"),
            "user_sentiment": user_sentiment.model_dump(mode="json"),
            "swot": swot.model_dump(mode="json"),
            "current_phase": "analyzing",
        }
