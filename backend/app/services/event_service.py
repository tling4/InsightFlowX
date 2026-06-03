import asyncio
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sa_func
from app.db.models.workflow_event import WorkflowEvent
from app.schemas.event import EventType


class EventLogger:
    """每个工作流执行实例化一个，管理事件写入和 seq 递增。
    """
    def __init__(
        self,
        db: AsyncSession,
        workflow_id: uuid.UUID,
        execution_attempt: int,
        run_id: uuid.UUID | None = None,
        node_name: str = "",
        iteration: int = 0,
        seq_state: dict[str, int | None] | None = None,
        lock: asyncio.Lock | None = None,
    ):
        self.db = db
        self.workflow_id = workflow_id
        self.execution_attempt = execution_attempt
        self.run_id = run_id
        self.node_name = node_name
        self.iteration = iteration
        self._seq_state = seq_state if seq_state is not None else {"value": None}
        self._lock = lock or asyncio.Lock()

    async def _next_seq(self) -> int:
        if self._seq_state["value"] is None:
            result = await self.db.execute(
                select(sa_func.coalesce(sa_func.max(WorkflowEvent.seq), 0))
                .where(WorkflowEvent.workflow_id == self.workflow_id)
            )
            self._seq_state["value"] = result.scalar_one()
        self._seq_state["value"] += 1
        return self._seq_state["value"]

    async def log(
        self,
        event_type: EventType,
        payload: dict | None = None,
        node_name: str | None = None,
        iteration: int | None = None,
    ) -> WorkflowEvent:
        async with self._lock:
            seq = await self._next_seq()
            event = WorkflowEvent(
                id=uuid.uuid4(),
                workflow_id=self.workflow_id,
                run_id=self.run_id,
                node_name=node_name or self.node_name,
                iteration=iteration if iteration is not None else self.iteration,
                event_type=event_type.value,
                seq=seq,
                execution_attempt=self.execution_attempt,
                payload=payload or {},
            )
            self.db.add(event)
            await self.db.commit()
            return event

    def with_node(self, node_name: str, iteration: int = 0) -> "EventLogger":
        return EventLogger(
            db=self.db,
            workflow_id=self.workflow_id,
            execution_attempt=self.execution_attempt,
            run_id=self.run_id,
            node_name=node_name,
            iteration=iteration,
            seq_state=self._seq_state,
            lock=self._lock,
        )
