import time
import uuid
from app.agents.base_agent import BaseAgent
from app.services.event_service import EventLogger
from app.schemas.event import EventType
from app.schemas.competitor import CompetitorInfo


class CollectionAgent(BaseAgent):
    node_name = "information_collection"

    async def run(self, state: dict, event_logger: EventLogger, workflow_id: uuid.UUID) -> dict:
        """Stub：竞品信息采集节点。当前返回空结构和事件记录，等待 LLM 集成。"""
        config = state.get("config", {})
        competitor_names = config.get("competitors", []) if isinstance(config, dict) else []

        await self.log_and_broadcast(event_logger, EventType.NODE_START, {
            "input_summary": {
                "competitors_count": len(competitor_names),
                "phase": "collecting",
            },
        }, workflow_id)

        start = time.time()

        raw_data: dict[str, list] = {}
        collection_errors: dict[str, str] = {}
        competitors = []
        for name in competitor_names:
            raw_data[name] = []
            competitors.append(CompetitorInfo(name=name).model_dump(mode="json"))

        duration_ms = int((time.time() - start) * 1000)

        await self.log_and_broadcast(event_logger, EventType.NODE_COMPLETE, {
            "output_summary": {
                "collected_competitors": len(raw_data),
                "total_sources": 0,
                "failed_competitors": 0,
            },
            "duration_ms": duration_ms,
        }, workflow_id)

        return {
            "raw_data": raw_data,
            "collection_errors": collection_errors,
            "competitors": competitors,
            "context_summaries": {},
            "current_phase": "collecting",
        }
