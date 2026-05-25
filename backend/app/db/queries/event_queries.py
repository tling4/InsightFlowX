import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sa_func
from app.db.models.workflow_event import WorkflowEvent
from app.db.models.workflow_node_state import WorkflowNodeState


async def get_events(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    node_name: Optional[str] = None,
    event_type: Optional[str] = None,
    execution_attempt: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[WorkflowEvent]:
    stmt = select(WorkflowEvent).where(WorkflowEvent.workflow_id == workflow_id)
    if node_name:
        stmt = stmt.where(WorkflowEvent.node_name == node_name)
    if event_type:
        stmt = stmt.where(WorkflowEvent.event_type == event_type)
    if execution_attempt is not None:
        stmt = stmt.where(WorkflowEvent.execution_attempt == execution_attempt)
    stmt = stmt.order_by(WorkflowEvent.seq).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_events(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    node_name: Optional[str] = None,
    event_type: Optional[str] = None,
    execution_attempt: Optional[int] = None,
) -> int:
    stmt = select(sa_func.count(WorkflowEvent.id)).where(WorkflowEvent.workflow_id == workflow_id)
    if node_name:
        stmt = stmt.where(WorkflowEvent.node_name == node_name)
    if event_type:
        stmt = stmt.where(WorkflowEvent.event_type == event_type)
    if execution_attempt is not None:
        stmt = stmt.where(WorkflowEvent.execution_attempt == execution_attempt)
    result = await db.execute(stmt)
    return result.scalar_one()


async def get_node_states(db: AsyncSession, workflow_id: uuid.UUID, execution_attempt: Optional[int] = None) -> list[WorkflowNodeState]:
    stmt = select(WorkflowNodeState).where(WorkflowNodeState.workflow_id == workflow_id)
    if execution_attempt is not None:
        stmt = stmt.where(WorkflowNodeState.execution_attempt == execution_attempt)
    stmt = stmt.order_by(WorkflowNodeState.created_at)
    result = await db.execute(stmt)
    return list(result.scalars().all())
