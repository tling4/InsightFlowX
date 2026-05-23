import uuid
from app.services.event_service import EventLogger
from app.services.sse_service import sse_manager
from app.schemas.event import EventType


class BaseAgent:
    """DAG Agent 基类，提供事件记录 + SSE 广播钩子。"""

    node_name: str = ""

    async def log_and_broadcast(
        self,
        event_logger: EventLogger,
        event_type: EventType,
        payload: dict,
        workflow_id: uuid.UUID,
    ) -> None:
        event = await event_logger.log(event_type=event_type, payload=payload)
        await sse_manager.broadcast(workflow_id, {
            "event_type": event_type.value,
            "node_name": event.node_name,
            "seq": event.seq,
            "payload": payload,
            "created_at": str(event.created_at),
        })
