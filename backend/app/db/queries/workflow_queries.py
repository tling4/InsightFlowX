import uuid
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models.workflow import Workflow, InterviewMessageModel


async def get_workflow_by_id(db: AsyncSession, workflow_id: str | uuid.UUID, owner_id: uuid.UUID) -> Workflow | None:
    if not isinstance(workflow_id, uuid.UUID):
        workflow_id = uuid.UUID(workflow_id)
    result = await db.execute(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.owner_id == owner_id)
    )
    return result.scalar_one_or_none()


async def get_workflow_by_uuid(db: AsyncSession, workflow_id: uuid.UUID) -> Workflow | None:
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    return result.scalar_one_or_none()


async def get_user_workflows(db: AsyncSession, owner_id: uuid.UUID, limit: int = 20) -> List[Workflow]:
    result = await db.execute(
        select(Workflow).where(Workflow.owner_id == owner_id).order_by(Workflow.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_message_history(db: AsyncSession, workflow_id: uuid.UUID) -> List[InterviewMessageModel]:
    result = await db.execute(
        select(InterviewMessageModel).where(InterviewMessageModel.workflow_id == workflow_id).order_by(InterviewMessageModel.created_at)
    )
    return result.scalars().all()
