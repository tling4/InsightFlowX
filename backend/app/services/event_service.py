import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sa_func
from app.db.models.workflow_event import WorkflowEvent
from app.schemas.event import EventType


class EventLogger:
    """每个工作流执行实例化一个，管理事件写入和 seq 递增。

    seq 递增策略（lazy init）：
      - 首次调用 _next_seq 时查询库中当前最大值作为起点
      - 后续仅在内存中递增，避免每次写入都查库
    """

    def __init__(self, db: AsyncSession, workflow_id: uuid.UUID, node_name: str = "", iteration: int = 0):
        self.db = db
        self.workflow_id = workflow_id
        self.node_name = node_name
        self.iteration = iteration
        self._seq_counter: int | None = None

    async def _next_seq(self) -> int:
        if self._seq_counter is None:
            result = await self.db.execute(
                select(sa_func.coalesce(sa_func.max(WorkflowEvent.seq), 0))
                .where(WorkflowEvent.workflow_id == self.workflow_id)
            )
            self._seq_counter = result.scalar_one()
        self._seq_counter += 1
        return self._seq_counter

    async def log(
        self,
        event_type: EventType,
        payload: dict | None = None,
        node_name: str | None = None,
        iteration: int | None = None,
    ) -> WorkflowEvent:
        seq = await self._next_seq()
        event = WorkflowEvent(
            id=uuid.uuid4(),
            workflow_id=self.workflow_id,
            node_name=node_name or self.node_name,
            iteration=iteration if iteration is not None else self.iteration,
            event_type=event_type.value,
            seq=seq,
            payload=payload or {},
        )
        self.db.add(event)
        await self.db.commit()
        return event

    def with_node(self, node_name: str, iteration: int = 0) -> "EventLogger":
        """派生一个子 Logger，共享父 Logger 的 seq 计数器但使用不同的 node_name/iteration。"""
        new_logger = EventLogger(self.db, self.workflow_id, node_name, iteration)
        new_logger._seq_counter = self._seq_counter
        return new_logger
