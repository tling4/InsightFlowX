import uuid
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models.artifact import Artifact
from app.db.models.trace_link import TraceLink


async def get_workflow_artifacts(db: AsyncSession, workflow_id: uuid.UUID) -> list[Artifact]:
    result = await db.execute(
        select(Artifact).where(Artifact.workflow_id == workflow_id).order_by(Artifact.created_at)
    )
    return list(result.scalars().all())


async def get_artifact_by_id(db: AsyncSession, artifact_id: uuid.UUID) -> Artifact | None:
    result = await db.execute(select(Artifact).where(Artifact.id == artifact_id))
    return result.scalar_one_or_none()


async def get_artifact_ids_by_workflow(db: AsyncSession, workflow_id: uuid.UUID) -> List[uuid.UUID]:
    result = await db.execute(
        select(Artifact.id).where(Artifact.workflow_id == workflow_id)
    )
    return [row[0] for row in result.all()]


async def get_trace_links(db: AsyncSession, artifact_ids: list[uuid.UUID]) -> list[TraceLink]:
    result = await db.execute(
        select(TraceLink).where(TraceLink.artifact_id.in_(artifact_ids)).order_by(TraceLink.created_at)
    )
    return list(result.scalars().all())
