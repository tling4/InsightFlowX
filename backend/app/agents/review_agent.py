import time
import uuid
from app.agents.base_agent import BaseAgent
from app.services.event_service import EventLogger
from app.schemas.event import EventType
from app.schemas.review import ReviewOutput, ReviewCheck


class ReviewAgent(BaseAgent):
    node_name = "review"

    async def run(self, state: dict, event_logger: EventLogger, workflow_id: uuid.UUID) -> dict:
        """Stub：质量审查节点。默认全部通过，等待 LLM 驱动的审查逻辑集成。"""
        await self.log_and_broadcast(event_logger, EventType.NODE_START, {
            "input_summary": {"phase": "reviewing"},
        }, workflow_id)

        start = time.time()

        review = ReviewOutput(
            passed=True,
            score=100.0,
            checks=[
                ReviewCheck(dimension="completeness", passed=True, detail="Stub: 自动通过"),
                ReviewCheck(dimension="accuracy", passed=True, detail="Stub: 自动通过"),
                ReviewCheck(dimension="consistency", passed=True, detail="Stub: 自动通过"),
                ReviewCheck(dimension="credibility", passed=True, detail="Stub: 自动通过"),
            ],
            feedback="Stub 审查: 自动通过",
            target_node=None,
            specific_issues=[],
        )

        duration_ms = int((time.time() - start) * 1000)

        await self.log_and_broadcast(event_logger, EventType.REVIEW_PASS, {
            "score": review.score,
            "checks": [c.model_dump(mode="json") for c in review.checks],
            "feedback": review.feedback,
        }, workflow_id)

        await self.log_and_broadcast(event_logger, EventType.NODE_COMPLETE, {
            "output_summary": {"passed": True, "score": 100.0},
            "duration_ms": duration_ms,
        }, workflow_id)

        return {
            "review_result": review.model_dump(mode="json"),
            "current_phase": "reviewing",
        }
