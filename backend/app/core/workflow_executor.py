"""工作流执行编排器 —— 将模板、运行时、持久化层串联为完整执行生命周期。

提供三个对外入口函数，由 API 层通过 BackgroundTasks 调用：
    run_workflow(workflow_id)      首次执行
    resume_workflow(workflow_id, decision)  人工决策后恢复
    recover_workflow(workflow_id)  僵尸恢复（进程崩溃 / 超时后）

执行流程（以 run_workflow 为例）：
    1. _get_or_create_run    创建/复用 WorkflowRun 记录
    2. _make_runtime         构建 GraphRuntime（注入 checkpointer）
    3. runtime.ainvoke       编译并执行 StateGraph
    4. _handle_graph_result  解析最终状态 → 暂停 / 完成 / 失败
    5. 异常路径 → _handle_graph_exception（包含 GraphInterrupt 安全网）

内部模块依赖：
    competitive_template  → GraphTemplate + make_initial_data
    pause_service         → 暂停生命周期管理（extract / persist / resolve）
    runtime               → GraphRuntime（编译 + 执行）
    retry.NodeFatalError  → 统一错误信息提取
"""

import logging
import uuid
from datetime import datetime, timezone

from langgraph.errors import GraphInterrupt
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.dependency.checkpointer import get_checkpointer
from app.core.competitive_template import CompetitiveAnalysisTemplate, make_initial_data
from app.core.pause_service import extract_interrupt_payload, make_pause_state, persist_pause, resolve_pause
from app.core.runtime.retry import NodeFatalError
from app.core.runtime import GraphRuntime
from app.db.models.workflow_event import WorkflowEvent
from app.db.models.workflow_run import WorkflowRun
from app.db.queries.workflow_queries import get_workflow_by_uuid
from app.db.session import async_session_factory
from app.exceptions import AppException
from app.schemas.decision import DecisionRequest
from app.schemas.event import EventType
from app.services.event_service import EventLogger
from app.services.sse_service import sse_manager

logger = logging.getLogger(__name__)


# ── 内部辅助函数 ─────────────────────────────────────────────────────────

def _thread_id(workflow_id: uuid.UUID, run_id: uuid.UUID) -> str:
    """生成 langgraph checkpoint 使用的 thread_id。

    格式: "{workflow_id}:{run_id}"
    """
    return f"{workflow_id}:{run_id}"


def _session_factory_for_engine(engine: AsyncEngine | None):
    """根据可选的引擎参数返回合适的会话工厂。

    engine 为 None 时使用全局 async_session_factory（默认数据库），
    否则为指定的引擎创建新工厂（用于测试等场景）。
    """
    if engine is None:
        return async_session_factory
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _extract_error_info(e: Exception) -> tuple[str, str, dict | None]:
    """从任意异常中提取标准化的错误信息三元组。

    优先使用 NodeFatalError.error_info（封装了 AppException 解包），
    其次直接处理 AppException，最后回退到通用异常字符串。

    Args:
        e: 捕获的异常
    Returns:
        (error_code, error_message, error_details) 三元组
    """
    if isinstance(e, NodeFatalError):
        return e.error_info
    if isinstance(e, AppException):
        return e.error_code, e.message, e.details
    return "EXECUTION_ERROR", str(e)[:1000], None


def _state_control(final_state: dict | None) -> dict:
    """从 RuntimeState 中安全提取 control 层。

    Args:
        final_state: GraphRuntime 返回的最终状态
    Returns:
        control dict，状态无效时返回空 dict
    """
    if not isinstance(final_state, dict):
        return {}
    control = final_state.get("control")
    return control if isinstance(control, dict) else {}


# ── 基础设施 ─────────────────────────────────────────────────────────────

async def _maybe_get_checkpointer(workflow_id: uuid.UUID):
    """尝试获取 Postgres checkpointer。

    如果 checkpointer 未初始化（例如测试环境），记录警告并返回 None，
    此时工作流仍可执行但不会持久化 checkpoint（无法恢复）。

    Args:
        workflow_id: 工作流 UUID（仅用于日志）
    Returns:
        AsyncPostgresSaver 或 None
    """
    try:
        return await get_checkpointer()
    except RuntimeError as exc:
        logger.warning("工作流 %s 未初始化 checkpointer，跳过执行: %s", workflow_id, exc)
        return None


async def _get_or_create_run(db: AsyncSession, workflow) -> WorkflowRun:
    """获取或创建当前工作流的执行实例。

    逻辑：
        1. 如果 workflow 已有 current_run_id 且状态为 running/paused，直接复用
        2. 否则创建新的 WorkflowRun，更新 workflow.current_run_id

    Args:
        db:       数据库会话
        workflow: Workflow ORM 对象
    Returns:
        当前有效的 WorkflowRun 实例
    """
    if workflow.current_run_id:
        current = await db.get(WorkflowRun, workflow.current_run_id)
        if current and current.status in ("running", "paused"):
            return current

    run = WorkflowRun(
        id=uuid.uuid4(),
        workflow_id=workflow.id,
        execution_attempt=workflow.execution_attempt,
        thread_id=_thread_id(workflow.id, uuid.uuid4()),
        status="running",
        entrypoint=CompetitiveAnalysisTemplate.entrypoint,
    )
    # thread_id 绑定到持久化的 run.id
    run.thread_id = _thread_id(workflow.id, run.id)
    db.add(run)
    # Workflow.current_run_id has a database-level FK to workflow_run.id.
    # Flush the run first because there is no ORM relationship that lets
    # SQLAlchemy infer the required INSERT-before-UPDATE ordering.
    await db.flush([run])
    workflow.current_run_id = run.id
    workflow.langgraph_checkpoint_id = run.thread_id
    await db.commit()
    await db.refresh(run)
    return run


async def _get_current_run(db: AsyncSession, workflow) -> WorkflowRun | None:
    """获取工作流最新的 WorkflowRun。

    先尝试 current_run_id，失败则按 started_at 降序查找最新记录。

    Args:
        db:       数据库会话
        workflow: Workflow ORM 对象
    Returns:
        WorkflowRun 或 None
    """
    if workflow.current_run_id:
        run = await db.get(WorkflowRun, workflow.current_run_id)
        if run:
            return run
    result = await db.execute(
        select(WorkflowRun)
        .where(WorkflowRun.workflow_id == workflow.id)
        .order_by(WorkflowRun.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _make_runtime(db, workflow, run, event_logger, checkpointer) -> GraphRuntime:
    """构建 GraphRuntime 实例。

    将当前工作流上下文注入到运行时中，所有三个入口函数共用此工厂。

    Args:
        db:           数据库会话
        workflow:     Workflow ORM 对象
        run:          WorkflowRun ORM 对象
        event_logger: EventLogger 实例
        checkpointer: AsyncPostgresSaver 或 None
    Returns:
        已配置的 GraphRuntime 实例
    """
    return GraphRuntime(
        template=CompetitiveAnalysisTemplate,
        db=db,
        workflow_id=workflow.id,
        run_id=run.id,
        execution_attempt=run.execution_attempt,
        thread_id=run.thread_id,
        event_logger=event_logger,
        checkpointer=checkpointer,
    )


# ── 图结果处理 ───────────────────────────────────────────────────────────

async def _handle_graph_result(workflow, run, db, event_logger: EventLogger, final_state: dict) -> None:
    """处理图执行完成后的最终状态。

    三种结果路径：
        1. 暂停（interrupt） → 设置 workflow.status="paused"，持久化暂停记录
        2. 失败（terminal_status="failed"） → 从 control 提取失败原因
        3. 完成（terminal_status="completed"） → 设置工作流完成状态

    Args:
        workflow:     Workflow ORM 对象
        run:          WorkflowRun ORM 对象
        db:           数据库会话
        event_logger: EventLogger 实例
        final_state:  GraphRuntime.ainvoke/aresume/arecover 的返回值
    """
    pause_data = extract_interrupt_payload(final_state)
    if pause_data is not None:
        workflow.status = "paused"
        workflow.current_phase = "reviewing"
        workflow.pause_state = make_pause_state(pause_data)
        run.status = "paused"
        await persist_pause(db, workflow, run, workflow.pause_state)
        await db.commit()
        await event_logger.log(EventType.WORKFLOW_PAUSED, workflow.pause_state, node_name=pause_data.get("paused_by_node", "review"))
        await sse_manager.broadcast(workflow.id, {"event_type": EventType.WORKFLOW_PAUSED.value, **workflow.pause_state})
        return

    control = _state_control(final_state)
    workflow.revision_count = int(control.get("revision_count", 0) or 0)

    if control.get("terminal_status") == "failed":
        workflow.status = "failed"
        workflow.error_message = control.get("terminal_reason") or "工作流执行失败"
        run.status = "failed"
        run.error_message = workflow.error_message
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await event_logger.log(
            EventType.WORKFLOW_FAILED,
            {
                "error_code": "WORKFLOW_FAILED",
                "error_message": workflow.error_message,
            },
            node_name="__workflow__",
        )
        await sse_manager.broadcast(workflow.id, {
            "event_type": EventType.WORKFLOW_FAILED.value,
            "error_code": "WORKFLOW_FAILED",
            "error_message": workflow.error_message[:200],
        })
        return

    workflow.status = "completed"
    workflow.current_phase = "done"
    workflow.completed_at = datetime.now(timezone.utc)
    workflow.pause_state = None
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await event_logger.log(EventType.WORKFLOW_COMPLETE, {}, node_name="__workflow__")
    await sse_manager.broadcast(workflow.id, {"event_type": EventType.WORKFLOW_COMPLETE.value})


async def _handle_graph_exception(workflow, run, db, event_logger: EventLogger, e: Exception) -> None:
    """处理图执行过程中抛出的异常。

    两种异常路径：
        1. GraphInterrupt —— langgraph 在无 checkpointer 时抛出的中断异常
           （安全网：正常情况由 _handle_graph_result 通过 __interrupt__ key 处理）
        2. 其他异常 —— 记录错误信息，设置工作流为 failed

    Args:
        workflow:     Workflow ORM 对象
        run:          WorkflowRun ORM 对象
        db:           数据库会话
        event_logger: EventLogger 实例
        e:            捕获的异常
    """
    if isinstance(e, GraphInterrupt):
        pause_data = e.args[0] if e.args else {}
        workflow.status = "paused"
        workflow.pause_state = make_pause_state(pause_data if isinstance(pause_data, dict) else {})
        run.status = "paused"
        await persist_pause(db, workflow, run, workflow.pause_state)
        await db.commit()
        await event_logger.log(EventType.WORKFLOW_PAUSED, workflow.pause_state, node_name=workflow.pause_state.get("paused_by_node", "review"))
        await sse_manager.broadcast(workflow.id, {"event_type": EventType.WORKFLOW_PAUSED.value, **workflow.pause_state})
        return

    logger.exception("工作流 %s 执行失败: %s", workflow.id, e)
    error_code, error_message, error_details = _extract_error_info(e)
    workflow.status = "failed"
    workflow.error_message = error_message
    run.status = "failed"
    run.error_message = error_message
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await event_logger.log(
        EventType.WORKFLOW_FAILED,
        {"error_code": error_code, "error_message": error_message, "error_details": error_details},
        node_name="__workflow__",
    )
    await sse_manager.broadcast(workflow.id, {
        "event_type": EventType.WORKFLOW_FAILED.value,
        "error_code": error_code,
        "error_message": error_message[:200],
    })


async def _get_last_event_time(db, workflow_id: uuid.UUID):
    """查询工作流最后一次事件的创建时间。

    用于僵尸恢复的时间判断 —— 如果 60s 内有事件，说明工作流仍在活跃运行中。

    Args:
        db:          数据库会话
        workflow_id: 工作流 UUID
    Returns:
        datetime 或 None
    """
    result = await db.execute(
        select(sa_func.max(WorkflowEvent.created_at)).where(WorkflowEvent.workflow_id == workflow_id)
    )
    return result.scalar_one_or_none()


# ── 公开 API ─────────────────────────────────────────────────────────────

async def run_workflow(workflow_id: uuid.UUID, engine: AsyncEngine | None = None) -> None:
    """首次启动工作流执行。

    完整流程：
        1. 获取 workflow，验证状态为 "running"
        2. 初始化 checkpointer
        3. 创建/复用 WorkflowRun
        4. 构建 GraphRuntime → ainvoke(make_initial_data(workflow))
        5. 处理结果（暂停 / 完成 / 失败）

    由 API 层通过 BackgroundTasks 调用。

    Args:
        workflow_id: 工作流 UUID
        engine:      可选的数据库引擎（默认使用全局配置）
    """
    session_factory = _session_factory_for_engine(engine)
    async with session_factory() as db:
        workflow = await get_workflow_by_uuid(db, workflow_id)
        if not workflow or workflow.status != "running":
            logger.warning("工作流 %s 不存在或状态不可执行", workflow_id)
            return

        checkpointer = await _maybe_get_checkpointer(workflow_id)
        if checkpointer is None:
            return

        try:
            run = await _get_or_create_run(db, workflow)
        except Exception as e:
            logger.exception("工作流 %s 初始化运行实例失败: %s", workflow_id, e)
            await db.rollback()
            workflow = await get_workflow_by_uuid(db, workflow_id)
            if workflow:
                workflow.status = "failed"
                workflow.error_message = f"工作流初始化失败: {str(e)[:900]}"
                await db.commit()
                await sse_manager.broadcast(workflow.id, {
                    "event_type": EventType.WORKFLOW_FAILED.value,
                    "error_code": "RUN_INITIALIZATION_ERROR",
                    "error_message": workflow.error_message[:200],
                })
                await sse_manager.close_workflow(workflow.id)
            return

        event_logger = EventLogger(db, workflow.id, run.execution_attempt, run_id=run.id)
        await event_logger.log(EventType.WORKFLOW_START, {"config": workflow.config, "run_id": str(run.id)}, node_name="__workflow__")
        await sse_manager.broadcast(workflow.id, {"event_type": EventType.WORKFLOW_START.value, "node_name": "__workflow__", "run_id": str(run.id)})

        try:
            runtime = _make_runtime(db, workflow, run, event_logger, checkpointer)
            final_state = await runtime.ainvoke(make_initial_data(workflow))
            await _handle_graph_result(workflow, run, db, event_logger, final_state)
        except Exception as e:
            await _handle_graph_exception(workflow, run, db, event_logger, e)
        finally:
            if workflow.status != "paused":
                await sse_manager.close_workflow(workflow.id)


async def resume_workflow(workflow_id: uuid.UUID, decision: DecisionRequest, engine: AsyncEngine | None = None) -> None:
    """人工决策后恢复暂停的工作流。

    完整流程：
        1. 获取 paused 状态的 workflow
        2. resolve_pause    —— 标记暂停为已解决 + 记录决策
        3. runtime.aresume  —— 用 Command(resume=decision) 从 checkpoint 继续
        4. 处理结果（暂停 / 完成 / 失败）

    由 API 层在 POST /{workflow_id}/decide 后通过 BackgroundTasks 调用。

    Args:
        workflow_id: 工作流 UUID
        decision:    用户决策（action + target_node + feedback）
        engine:      可选的数据库引擎
    """
    session_factory = _session_factory_for_engine(engine)
    async with session_factory() as db:
        workflow = await get_workflow_by_uuid(db, workflow_id)
        if not workflow or workflow.status != "paused":
            logger.warning("工作流 %s 不存在或状态不可恢复", workflow_id)
            return

        checkpointer = await _maybe_get_checkpointer(workflow_id)
        if checkpointer is None:
            return

        run = await _get_current_run(db, workflow)
        if not run:
            logger.error("工作流 %s 没有可恢复 run", workflow_id)
            return

        decision_payload = decision.model_dump(mode="json", exclude_none=True)
        await resolve_pause(db, workflow, run, decision_payload)
        workflow.status = "running"
        workflow.pause_state = None
        run.status = "running"
        await db.commit()

        event_logger = EventLogger(db, workflow.id, run.execution_attempt, run_id=run.id)
        await event_logger.log(EventType.WORKFLOW_RESUMED, decision_payload, node_name="__workflow__")
        await sse_manager.broadcast(workflow.id, {"event_type": EventType.WORKFLOW_RESUMED.value, **decision_payload})

        try:
            runtime = _make_runtime(db, workflow, run, event_logger, checkpointer)
            final_state = await runtime.aresume(decision_payload)
            await _handle_graph_result(workflow, run, db, event_logger, final_state)
        except Exception as e:
            await _handle_graph_exception(workflow, run, db, event_logger, e)
        finally:
            if workflow.status != "paused":
                await sse_manager.close_workflow(workflow.id)


async def recover_workflow(workflow_id: uuid.UUID, engine: AsyncEngine | None = None) -> None:
    """僵尸恢复 —— 从 checkpoint 继续可能已超时/崩溃的工作流。

    安全检查：
        - 如果最近 60s 内有过事件，说明仍在活跃运行，跳过
        - 否则从最后一个 langgraph checkpoint 继续执行

    使用 runtime.arecover()（不传 resume 值），
    langgraph 会自动从 checkpoint 处继续。

    Args:
        workflow_id: 工作流 UUID
        engine:      可选的数据库引擎
    """
    session_factory = _session_factory_for_engine(engine)
    async with session_factory() as db:
        workflow = await get_workflow_by_uuid(db, workflow_id)
        if not workflow or workflow.status != "running":
            logger.warning("工作流 %s 不存在或状态不可恢复", workflow_id)
            return

        last_event_time = await _get_last_event_time(db, workflow_id)
        if last_event_time is not None:
            age = (datetime.now(timezone.utc) - last_event_time.replace(tzinfo=timezone.utc)).total_seconds()
            if age < 60:
                logger.info("工作流 %s 最近 %.0fs 前有事件，跳过恢复", workflow_id, age)
                return

        checkpointer = await _maybe_get_checkpointer(workflow_id)
        if checkpointer is None:
            return

        run = await _get_current_run(db, workflow)
        if not run:
            logger.error("工作流 %s 没有可恢复 run", workflow_id)
            return

        event_logger = EventLogger(db, workflow.id, run.execution_attempt, run_id=run.id)
        try:
            runtime = _make_runtime(db, workflow, run, event_logger, checkpointer)
            final_state = await runtime.arecover()
            await _handle_graph_result(workflow, run, db, event_logger, final_state)
        except Exception as e:
            await _handle_graph_exception(workflow, run, db, event_logger, e)
        finally:
            if workflow.status != "paused":
                await sse_manager.close_workflow(workflow.id)
