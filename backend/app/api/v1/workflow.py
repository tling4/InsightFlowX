from fastapi import APIRouter, BackgroundTasks, Body, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_async_session
from app.dependencies import get_current_user
from app.schemas.auth import UserResponse
from app.schemas.workflow import WorkflowConfig, WorkflowCreate, WorkflowUpdate
from app.schemas.decision import DecisionRequest
from app.db.queries.workflow_queries import get_workflow_by_id, get_user_workflows
from app.services.workflow_service import create_workflow, update_workflow_title, start_workflow, cancel_workflow, delete_workflow, restart_workflow
from app.services.sse_service import sse_manager
from app.services.event_service import EventLogger
from app.schemas.event import EventType
from app.core.workflow_executor import run_workflow, resume_workflow, recover_workflow
from app.exceptions import WorkflowNotFoundError, InvalidStateTransitionError
from app.db.models.workflow_run import WorkflowRun
from app.db.models.workflow_pause import WorkflowPause
from sqlalchemy import select
from datetime import datetime, timezone


router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_new_workflow(
    body: WorkflowCreate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    workflow = await create_workflow(db, current_user.id, body.title)
    return {"workflow_id": str(workflow.id), "title": workflow.title, "status": workflow.status}


@router.get("")
async def list_my_workflows(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    workflows = await get_user_workflows(db, current_user.id)
    return [{"id": str(w.id), "title": w.title, "status": w.status, "created_at": w.created_at} for w in workflows]


@router.get("/{workflow_id}")
async def get_workflow_detail(
    workflow_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    return {
        "id": str(workflow.id),
        "title": workflow.title,
        "status": workflow.status,
        "current_phase": workflow.current_phase,
        "config": workflow.config,
        "revision_count": workflow.revision_count,
        "execution_attempt": workflow.execution_attempt,
        "current_run_id": str(workflow.current_run_id) if workflow.current_run_id else None,
        "max_revisions": workflow.max_revisions,
        "total_tokens": workflow.total_tokens,
        "error_message": workflow.error_message,
        "pause_state": workflow.pause_state,
        "created_at": workflow.created_at,
        "updated_at": workflow.updated_at,
        "completed_at": workflow.completed_at,
    }


@router.post("/{workflow_id}/start")
async def start_workflow_endpoint(
    workflow_id: str,
    background_tasks: BackgroundTasks,
    override_config: WorkflowConfig | None = Body(default=None),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """确认配置后启动 DAG 执行。

    可选的请求体为完整 WorkflowConfig，会覆盖访谈阶段持久化的 workflow.config，
    使右侧面板用户编辑成为权威配置（覆盖 LLM 未提取或提取错误的字段）。
    """
    workflow = await start_workflow(db, workflow_id, current_user.id, override_config)
    background_tasks.add_task(run_workflow, workflow.id, db.bind)
    return {"workflow_id": str(workflow.id), "status": workflow.status}


@router.patch("/{workflow_id}")
async def update_workflow_endpoint(
    workflow_id: str,
    body: WorkflowUpdate,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    workflow = await update_workflow_title(db, workflow_id, current_user.id, body.title)
    return {"workflow_id": str(workflow.id), "title": workflow.title, "status": workflow.status}


@router.delete("/{workflow_id}")
async def delete_workflow_endpoint(
    workflow_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """删除工作流。非终态先取消，终态直接删除。"""
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    if workflow.status not in ("completed", "cancelled", "failed"):
        await cancel_workflow(db, workflow_id, current_user.id)
    await delete_workflow(db, workflow_id, current_user.id)
    return {"detail": "工作流已删除"}


@router.post("/{workflow_id}/retry/{node_name}")
async def retry_node_endpoint(
    workflow_id: str,
    node_name: str,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """重试失败的工作流，从零开始重新执行。"""
    workflow = await restart_workflow(db, workflow_id, current_user.id)
    background_tasks.add_task(run_workflow, workflow.id, db.bind)
    return {
        "workflow_id": str(workflow.id),
        "status": "running",
        "execution_attempt": workflow.execution_attempt,
        "retry_node": node_name,
    }


@router.post("/{workflow_id}/recover")
async def recover_workflow_endpoint(
    workflow_id: str,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """从服务中断中恢复工作流执行，利用 LangGraph checkpoint 从断点继续。"""
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    if workflow.status != "running":
        raise InvalidStateTransitionError(workflow_id, workflow.status, "recover")
    background_tasks.add_task(recover_workflow, workflow.id, db.bind)
    return {"workflow_id": str(workflow.id), "status": "running", "action": "recover"}


@router.post("/{workflow_id}/decide")
async def human_decide(
    workflow_id: str,
    decision: DecisionRequest,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """人在回路决策端点。

    - jump:   从 checkpoint 恢复，跳转到指定 target_node 重新执行
    - drop_competitor: 移除问题竞品后恢复执行
    - keep_with_insufficient_evidence: 保留问题竞品，但允许证据不足继续
    - replace_competitor: 用新的竞品替换问题竞品后恢复执行
    - approve: 强制接受当前结果，标记 completed
    - abort:   放弃执行，标记 cancelled
    """
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    if workflow.status != "paused":
        raise InvalidStateTransitionError(workflow_id, workflow.status, "decide")

    if decision.action == "approve":
        run = await db.get(WorkflowRun, workflow.current_run_id) if workflow.current_run_id else None
        event_logger = EventLogger(db, workflow.id, workflow.execution_attempt, run_id=run.id if run else None)
        await event_logger.log(
            event_type=EventType.WORKFLOW_COMPLETE,
            payload={"approved_by_user": True},
            node_name="__workflow__",
        )
        await sse_manager.broadcast(workflow.id, {
            "event_type": EventType.WORKFLOW_COMPLETE.value,
        })
        workflow.status = "completed"
        workflow.current_phase = "done"
        workflow.pause_state = None
        workflow.completed_at = datetime.now(timezone.utc)
        if run:
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
        await _resolve_current_pauses(db, workflow.id, run.id if run else None, decision.model_dump(mode="json", exclude_none=True))
        await db.commit()
        await sse_manager.close_workflow(workflow.id)
        return {"workflow_id": str(workflow.id), "status": "completed", "action": "approve"}

    if decision.action == "abort":
        run = await db.get(WorkflowRun, workflow.current_run_id) if workflow.current_run_id else None
        event_logger = EventLogger(db, workflow.id, workflow.execution_attempt, run_id=run.id if run else None)
        await event_logger.log(
            event_type=EventType.WORKFLOW_FAILED,
            payload={"error_code": "USER_ABORTED", "error_message": "用户手动放弃"},
            node_name="__workflow__",
        )
        await sse_manager.broadcast(workflow.id, {
            "event_type": EventType.WORKFLOW_FAILED.value,
            "error_code": "USER_ABORTED",
        })
        workflow.status = "cancelled"
        workflow.pause_state = None
        if run:
            run.status = "cancelled"
            run.completed_at = datetime.now(timezone.utc)
        await _resolve_current_pauses(db, workflow.id, run.id if run else None, decision.model_dump(mode="json", exclude_none=True))
        await db.commit()
        await sse_manager.close_workflow(workflow.id)
        return {"workflow_id": str(workflow.id), "status": "cancelled", "action": "abort"}

    # jump: 启动后台恢复任务
    background_tasks.add_task(resume_workflow, workflow.id, decision, db.bind)
    return {
        "workflow_id": str(workflow.id),
        "status": "running",
        "action": decision.action.value,
        "target_node": decision.target_node,
    }


async def _resolve_current_pauses(db: AsyncSession, workflow_id, run_id, decision_payload: dict) -> None:
    stmt = select(WorkflowPause).where(
        WorkflowPause.workflow_id == workflow_id,
        WorkflowPause.is_resolved.is_(False),
    )
    if run_id is not None:
        stmt = stmt.where(WorkflowPause.run_id == run_id)
    result = await db.execute(stmt)
    for pause in result.scalars().all():
        pause.is_resolved = True
        pause.decision = decision_payload
        pause.resolved_at = datetime.now(timezone.utc)
