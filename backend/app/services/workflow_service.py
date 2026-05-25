import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.workflow import Workflow
from app.db.queries.workflow_queries import get_workflow_by_id
from app.exceptions import WorkflowNotFoundError, InvalidStateTransitionError, ConfigIncompleteError


async def create_workflow(db: AsyncSession, owner_id: uuid.UUID, title: str) -> Workflow:
    """创建工作流，初始状态为 configuring。"""
    workflow = Workflow(
        id=uuid.uuid4(),
        owner_id=owner_id,
        title=title,
        status="configuring"
    )
    db.add(workflow)
    await db.commit()
    await db.refresh(workflow)
    return workflow


async def confirm_interview(db: AsyncSession, workflow_id: str, owner_id: uuid.UUID) -> Workflow:
    """确认访谈配置已完成。要求状态为 configuring 且已配置 target_product。"""
    workflow = await get_workflow_by_id(db, workflow_id, owner_id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    if workflow.status != "configuring":
        raise InvalidStateTransitionError(workflow_id, workflow.status, "confirm")
    if not workflow.config or not workflow.config.get("target_product"):
        raise ConfigIncompleteError(workflow_id, missing_fields=["target_product"])
    return workflow


async def start_workflow(db: AsyncSession, workflow_id: str, owner_id: uuid.UUID) -> Workflow:
    """将工作流状态转为 running，准备启动后台任务。"""
    workflow = await get_workflow_by_id(db, workflow_id, owner_id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    if workflow.status != "configuring":
        raise InvalidStateTransitionError(workflow_id, workflow.status, "start")
    if not workflow.config or not workflow.config.get("target_product"):
        raise ConfigIncompleteError(workflow_id, missing_fields=["target_product"])
    workflow.status = "running"
    workflow.current_phase = "collecting"
    await db.commit()
    await db.refresh(workflow)
    return workflow


async def cancel_workflow(db: AsyncSession, workflow_id: str, owner_id: uuid.UUID) -> Workflow:
    """取消工作流。已 completed / cancelled 状态不允许重复取消。"""
    workflow = await get_workflow_by_id(db, workflow_id, owner_id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    if workflow.status in ("completed", "cancelled"):
        raise InvalidStateTransitionError(workflow_id, workflow.status, "cancel")
    workflow.status = "cancelled"
    await db.commit()
    await db.refresh(workflow)
    return workflow


async def delete_workflow(db: AsyncSession, workflow_id: str, owner_id: uuid.UUID) -> None:
    """物理删除工作流（级联删除所有关联数据）。"""
    workflow = await get_workflow_by_id(db, workflow_id, owner_id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    await db.delete(workflow)
    await db.commit()
