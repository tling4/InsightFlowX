import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from app.db.models.workflow import Workflow
from app.db.queries.workflow_queries import get_workflow_by_id
from app.exceptions import WorkflowNotFoundError, InvalidStateTransitionError, ConfigIncompleteError
from app.schemas.workflow import WorkflowConfig


AUTO_TITLE_PLACEHOLDERS = {
    "未命名分析",
    "未命名竞品分析",
    "新建竞品分析",
}


def build_workflow_title(config: WorkflowConfig | dict | None) -> str | None:
    """Build a concise title from the confirmed analysis target."""
    if isinstance(config, WorkflowConfig):
        target_product = config.target_product
    elif isinstance(config, dict):
        target_product = config.get("target_product", "")
    else:
        target_product = ""
    target_product = " ".join(str(target_product).split()).strip()
    if not target_product:
        return None
    if target_product.endswith("竞品分析"):
        return target_product[:255]
    return f"{target_product} 竞品分析"[:255]


def apply_auto_workflow_title(workflow: Workflow, config: WorkflowConfig | dict | None) -> bool:
    """Apply an inferred title without overwriting a user-authored title."""
    title = build_workflow_title(config)
    if not title:
        return False

    current_title = " ".join(str(workflow.title or "").split()).strip()
    previous_auto_title = build_workflow_title(workflow.config)
    if current_title not in AUTO_TITLE_PLACEHOLDERS and current_title != previous_auto_title:
        return False

    workflow.title = title
    return True


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


async def update_workflow_title(
    db: AsyncSession,
    workflow_id: str,
    owner_id: uuid.UUID,
    title: str,
) -> Workflow:
    """更新工作流标题。"""
    workflow = await get_workflow_by_id(db, workflow_id, owner_id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    workflow.title = title
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
    if apply_auto_workflow_title(workflow, workflow.config):
        await db.commit()
        await db.refresh(workflow)
    return workflow


async def start_workflow(
    db: AsyncSession,
    workflow_id: str,
    owner_id: uuid.UUID,
    override_config: WorkflowConfig | None = None,
) -> Workflow:
    """将工作流状态转为 running，准备启动后台任务。

    若 override_config 非 None，则在状态校验前以其覆盖 workflow.config。
    使前端右侧面板的用户编辑成为最终配置（避免 LLM 提取失败时配置永远不完整）。
    """
    workflow = await get_workflow_by_id(db, workflow_id, owner_id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    if workflow.status != "configuring":
        raise InvalidStateTransitionError(workflow_id, workflow.status, "start")
    if override_config is not None:
        apply_auto_workflow_title(workflow, override_config)
        workflow.config = override_config.model_dump(mode="json")
        # JSON 列原地赋值时 SQLAlchemy 不会自动检测变更，需手动标记
        flag_modified(workflow, "config")
    else:
        apply_auto_workflow_title(workflow, workflow.config)
    if not workflow.config or not workflow.config.get("target_product"):
        raise ConfigIncompleteError(workflow_id, missing_fields=["target_product"])
    workflow.status = "running"
    workflow.current_phase = "collecting"
    workflow.current_run_id = None
    workflow.pause_state = None
    workflow.error_message = None
    await db.commit()
    await db.refresh(workflow)
    return workflow


async def restart_workflow(
    db: AsyncSession,
    workflow_id: str,
    owner_id: uuid.UUID,
) -> Workflow:
    """Restart a workflow from a fresh execution attempt.

    Keeps the saved config, but clears runtime fields that belong to the
    previous attempt so the next run starts from a clean graph checkpoint
    namespace.
    """
    workflow = await get_workflow_by_id(db, workflow_id, owner_id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    if workflow.status not in ("failed", "paused"):
        raise InvalidStateTransitionError(workflow_id, workflow.status, "retry")

    workflow.status = "running"
    workflow.current_phase = "collecting"
    workflow.error_message = None
    workflow.pause_state = None
    workflow.completed_at = None
    workflow.revision_count = 0
    workflow.total_tokens = 0
    workflow.execution_attempt += 1
    workflow.langgraph_checkpoint_id = None
    workflow.current_run_id = None
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
