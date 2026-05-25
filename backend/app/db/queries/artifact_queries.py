import uuid
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models.artifact import Artifact
from app.db.models.trace_link import TraceLink


async def get_workflow_artifacts(db: AsyncSession, workflow_id: uuid.UUID, execution_attempt: int | None = None) -> list[Artifact]:
    stmt = select(Artifact).where(Artifact.workflow_id == workflow_id)
    if execution_attempt is not None:
        stmt = stmt.where(Artifact.execution_attempt == execution_attempt)
    stmt = stmt.order_by(Artifact.created_at)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_artifact_by_id(db: AsyncSession, artifact_id: uuid.UUID) -> Artifact | None:
    result = await db.execute(select(Artifact).where(Artifact.id == artifact_id))
    return result.scalar_one_or_none()


async def get_artifact_ids_by_workflow(db: AsyncSession, workflow_id: uuid.UUID, execution_attempt: int | None = None) -> List[uuid.UUID]:
    stmt = select(Artifact.id).where(Artifact.workflow_id == workflow_id)
    if execution_attempt is not None:
        stmt = stmt.where(Artifact.execution_attempt == execution_attempt)
    result = await db.execute(stmt)
    return [row[0] for row in result.all()]


async def get_trace_links(db: AsyncSession, artifact_ids: list[uuid.UUID]) -> list[TraceLink]:
    result = await db.execute(
        select(TraceLink).where(TraceLink.artifact_id.in_(artifact_ids)).order_by(TraceLink.created_at)
    )
    return list(result.scalars().all())
