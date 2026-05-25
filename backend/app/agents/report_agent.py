import time
import uuid
from datetime import datetime
from app.agents.base_agent import BaseAgent
from app.services.event_service import EventLogger
from app.schemas.event import EventType
from app.schemas.report import ReportOutput


class ReportAgent(BaseAgent):
    node_name = "report_writing"

    async def run(self, state: dict, event_logger: EventLogger, workflow_id: uuid.UUID) -> dict:
        """Stub：报告生成节点。返回空 ReportOutput，等待 LLM 集成。"""
        config = state.get("config", {})
        target = config.get("target_product", "未知产品") if isinstance(config, dict) else "未知产品"

        await self.log_and_broadcast(event_logger, EventType.NODE_START, {
            "input_summary": {"phase": "writing", "target_product": target},
        }, workflow_id)

        start = time.time()

        report = ReportOutput(
            title=f"{target} 竞品分析报告",
            executive_summary="",
            sections=[],
            citations=[],
            full_markdown="",
            generated_at=datetime.utcnow(),
        )

        duration_ms = int((time.time() - start) * 1000)

        await self.log_and_broadcast(event_logger, EventType.NODE_COMPLETE, {
            "output_summary": {"sections_count": 0, "citations_count": 0},
            "duration_ms": duration_ms,
        }, workflow_id)

        return {
            "report": report.model_dump(mode="json"),
            "current_phase": "writing",
        }
