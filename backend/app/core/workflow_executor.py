import uuid
import logging
from datetime import datetime, timezone
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, AsyncSession
from langgraph.errors import GraphInterrupt
from langgraph.types import Command
from app.db.session import async_session_factory
from app.db.queries.workflow_queries import get_workflow_by_uuid
from app.db.models.workflow_event import WorkflowEvent
from app.core.orchestrator import compile_workflow_graph
from app.core.checkpointer import get_checkpointer
from app.services.event_service import EventLogger
from app.services.sse_service import sse_manager
from app.schemas.event import EventType
from app.schemas.decision import DecisionRequest
from app.exceptions import AppException
from app.core.node_executor import NodeFatalError

logger = logging.getLogger(__name__)


def _thread_id(workflow_id: uuid.UUID, execution_attempt: int) -> str:
    """Keep each execution attempt on its own LangGraph checkpoint thread."""
    return f"{workflow_id}:{execution_attempt}"


def _session_factory_for_engine(engine: AsyncEngine | None):
    if engine is None:
        return async_session_factory
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _extract_error_info(e: Exception) -> tuple[str, str, dict | None]:
    if isinstance(e, NodeFatalError) and isinstance(e.last_error, AppException):
        app_err = e.last_error
        return app_err.error_code, app_err.message, app_err.details
    if isinstance(e, AppException):
        return e.error_code, e.message, e.details
    return "EXECUTION_ERROR", str(e)[:1000], None


def _extract_interrupt_payload(final_state: dict | None) -> dict | None:
    if not isinstance(final_state, dict) or "__interrupt__" not in final_state:
        return None
    interrupt_value = final_state.get("__interrupt__")
    if isinstance(interrupt_value, (list, tuple)) and interrupt_value:
        interrupt_value = interrupt_value[0]
    if hasattr(interrupt_value, "value"):
        interrupt_value = interrupt_value.value
    elif isinstance(interrupt_value, dict) and "value" in interrupt_value:
        interrupt_value = interrupt_value["value"]
    return interrupt_value if isinstance(interrupt_value, dict) else {}


def _review_failed(final_state: dict | None) -> bool:
    if not isinstance(final_state, dict):
        return True
    review = final_state.get("review_result")
    if not isinstance(review, dict):
        return False
    return review.get("passed") is False


def _review_failure_message(final_state: dict | None) -> str:
    if not isinstance(final_state, dict):
        return "工作流未返回有效最终状态"
    review = final_state.get("review_result")
    if isinstance(review, dict):
        return str(review.get("feedback") or "报告质检未通过")[:1000]
    return "报告质检未通过"


def _make_pause_state(pause_data: dict) -> dict:
    return {
        "paused_by_node": pause_data.get("paused_by_node", ""),
        "pause_reason": pause_data.get("pause_reason", ""),
        "pause_options": pause_data.get("pause_options", []),
        "pause_context": pause_data.get("pause_context", {}),
        "dag_state": pause_data.get("dag_state", {}),
        "paused_at": datetime.now(timezone.utc).isoformat(),
    }


async def _handle_graph_result(
    workflow,
    db,
    event_logger: EventLogger,
    workflow_id: uuid.UUID,
    final_state: dict,
) -> None:
    """统一的 graph 成功执行后处理：pause / complete / failed 状态转换。"""
    pause_data = _extract_interrupt_payload(final_state)
    if pause_data is not None:
        workflow.status = "paused"
        workflow.pause_state = _make_pause_state(pause_data)
        workflow.current_phase = "reviewing"
        await db.commit()
        await event_logger.log(
            event_type=EventType.WORKFLOW_PAUSED,
            payload=workflow.pause_state,
            node_name=pause_data.get("paused_by_node", "review"),
        )
        await sse_manager.broadcast(workflow_id, {
            "event_type": EventType.WORKFLOW_PAUSED.value,
            **workflow.pause_state,
        })
        return

    if _review_failed(final_state):
        workflow.status = "failed"
        workflow.current_phase = "reviewing"
        workflow.revision_count = (
            final_state.get("revision_count", 0)
            if isinstance(final_state, dict)
            else workflow.revision_count
        )
        workflow.error_message = _review_failure_message(final_state)
        await db.commit()
        await event_logger.log(
            event_type=EventType.WORKFLOW_FAILED,
            payload={
                "error_code": "REVIEW_FAILED",
                "error_message": workflow.error_message,
                "error_details": final_state.get("review_result") if isinstance(final_state, dict) else None,
            },
            node_name="__workflow__",
        )
        await sse_manager.broadcast(workflow_id, {
            "event_type": EventType.WORKFLOW_FAILED.value,
            "error_code": "REVIEW_FAILED",
            "error_message": workflow.error_message[:200],
        })
        return

    workflow.status = "completed"
    workflow.current_phase = "done"
    workflow.revision_count = final_state.get("revision_count", 0) if isinstance(final_state, dict) else 0
    workflow.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await event_logger.log(
        event_type=EventType.WORKFLOW_COMPLETE,
        payload={},
        node_name="__workflow__",
    )
    await sse_manager.broadcast(workflow_id, {
        "event_type": EventType.WORKFLOW_COMPLETE.value,
    })


async def _handle_graph_exception(
    workflow,
    db,
    event_logger: EventLogger,
    workflow_id: uuid.UUID,
    e: Exception,
) -> None:
    """统一的 graph 异常处理：GraphInterrupt → paused，其他 → failed。"""
    if isinstance(e, GraphInterrupt):
        pause_data = e.args[0] if e.args else {}
        workflow.status = "paused"
        workflow.pause_state = _make_pause_state(pause_data)
        await db.commit()
        await event_logger.log(
            event_type=EventType.WORKFLOW_PAUSED,
            payload=workflow.pause_state,
            node_name=pause_data.get("paused_by_node", "review"),
        )
        await sse_manager.broadcast(workflow_id, {
            "event_type": EventType.WORKFLOW_PAUSED.value,
            **workflow.pause_state,
        })
        return

    logger.exception(f"工作流 {workflow_id} 执行失败: {e}")
    try:
        workflow.status = "failed"
        error_code, error_message, error_details = _extract_error_info(e)
        workflow.error_message = error_message
        await db.commit()
        await event_logger.log(
            event_type=EventType.WORKFLOW_FAILED,
            payload={
                "error_code": error_code,
                "error_message": error_message,
                "error_details": error_details,
            },
            node_name="__workflow__",
        )
        await sse_manager.broadcast(workflow_id, {
            "event_type": EventType.WORKFLOW_FAILED.value,
            "error_code": error_code,
            "error_message": error_message[:200],
        })
    except Exception:
        logger.exception(f"工作流 {workflow_id} 错误处理也失败")


async def _get_last_event_time(db, workflow_id: uuid.UUID):
    """查询工作流最近一条事件的创建时间，用于判断是否僵尸工作流。"""
    result = await db.execute(
        select(sa_func.max(WorkflowEvent.created_at)).where(
            WorkflowEvent.workflow_id == workflow_id
        )
    )
    return result.scalar_one_or_none()


async def _maybe_get_checkpointer(workflow_id: uuid.UUID):
    try:
        return await get_checkpointer()
    except RuntimeError as exc:
        logger.warning("宸ヤ綔娴?%s 鏈垵濮嬪寲 checkpointer锛屽凡璺宠繃涓嬫父鎵ц: %s", workflow_id, exc)
        return None


async def run_workflow(workflow_id: uuid.UUID, engine: AsyncEngine | None = None) -> None:
    """BackgroundTasks 入口，运行完整 DAG。使用独立 DB session。

    生命周期：
      1. 校验工作流状态为 running
      2. 编译 LangGraph（带 PostgreSQL checkpointer），注入 initial state
      3. ainvoke 执行，成功后标记 completed
      4. GraphInterrupt → status = paused（人在回路）
      5. Exception → status = failed
    """
    session_factory = _session_factory_for_engine(engine)
    async with session_factory() as db:
        workflow = await get_workflow_by_uuid(db, workflow_id)
        if not workflow:
            logger.error(f"工作流 {workflow_id} 不存在")
            return
        if workflow.status != "running":
            logger.warning(f"工作流 {workflow_id} 状态为 {workflow.status}，跳过执行")
            return

        execution_attempt = workflow.execution_attempt
        event_logger = EventLogger(db, workflow_id, execution_attempt)
        checkpointer = await _maybe_get_checkpointer(workflow_id)
        if checkpointer is None:
            return

        await event_logger.log(
            event_type=EventType.WORKFLOW_START,
            payload={"config": workflow.config},
            node_name="__workflow__",
        )
        await sse_manager.broadcast(workflow_id, {
            "event_type": EventType.WORKFLOW_START.value,
            "node_name": "__workflow__",
        })

        try:
            compiled_graph = compile_workflow_graph(
                db, workflow_id, event_logger, execution_attempt, checkpointer,
            )
            config = {"configurable": {"thread_id": _thread_id(workflow_id, execution_attempt)}}

            initial_state = {
                "config": workflow.config,
                "competitors": [],
                "raw_data": {},
                "collection_errors": {},
                "context_summaries": {},
                "feature_matrix": None,
                "pricing_comparison": None,
                "user_sentiment": None,
                "swot": None,
                "report": None,
                "review_result": None,
                "revision_count": 0,
                "max_revisions": workflow.max_revisions,
                "current_phase": "collecting",
                "workflow_status": "running",
                "errors": [],
                "messages": [],
            }

            final_state = await compiled_graph.ainvoke(initial_state, config)
            await _handle_graph_result(workflow, db, event_logger, workflow_id, final_state)

        except Exception as e:
            await _handle_graph_exception(workflow, db, event_logger, workflow_id, e)

        finally:
            if workflow.status != "paused":
                await sse_manager.close_workflow(workflow_id)


async def resume_workflow(
    workflow_id: uuid.UUID,
    decision: DecisionRequest,
    engine: AsyncEngine | None = None,
) -> None:
    """从暂停状态恢复 DAG 执行。

    使用 LangGraph Command(resume=...) 从最近一次 checkpoint 继续，
    interrupt() 调用点收到 decision 后继续执行。
    """
    session_factory = _session_factory_for_engine(engine)
    async with session_factory() as db:
        workflow = await get_workflow_by_uuid(db, workflow_id)
        if not workflow:
            logger.error(f"工作流 {workflow_id} 不存在")
            return
        if workflow.status != "paused":
            logger.warning(f"工作流 {workflow_id} 状态为 {workflow.status}，无法恢复")
            return

        event_logger = EventLogger(db, workflow_id, workflow.execution_attempt)
        checkpointer = await _maybe_get_checkpointer(workflow_id)
        if checkpointer is None:
            return

        # 在清空 pause_state 之前先快照 paused_by_node 和 dag_state，
        # 否则下方 cached_review_result 永远是 None（C1 的本意）
        paused_by_node_before = (workflow.pause_state or {}).get("paused_by_node")
        dag_state_before = (workflow.pause_state or {}).get("dag_state", {})

        workflow.status = "running"
        if decision.action == "jump":
            workflow.pause_state = None
        await db.commit()

        await event_logger.log(
            event_type=EventType.WORKFLOW_RESUMED,
            payload={
                "action": decision.action.value,
                "target_node": decision.target_node,
                "feedback": decision.feedback,
            },
            node_name="__workflow__",
        )
        await sse_manager.broadcast(workflow_id, {
            "event_type": EventType.WORKFLOW_RESUMED.value,
            "action": decision.action.value,
            "target_node": decision.target_node,
            "feedback": decision.feedback,
        })

        try:
            compiled_graph = compile_workflow_graph(
                db, workflow_id, event_logger, workflow.execution_attempt, checkpointer,
            )
            config = {"configurable": {"thread_id": _thread_id(workflow_id, workflow.execution_attempt)}}

            # 从 pause_state 快照（commit 前已保存）提取缓存的 review_result，
            # 避免 resume 时 ReviewAgent 重跑 LLM
            cached_review_result = dag_state_before.get("review_result") if decision.action == "jump" else None

            # 发出通用 REROUTE 事件
            if decision.action == "jump":
                target = decision.target_node or (
                    cached_review_result.get("target_node") if cached_review_result else None
                )
                if target:
                    await event_logger.log(
                        event_type=EventType.REROUTE,
                        payload={
                            "from_node": paused_by_node_before,
                            "to_node": target,
                            "trigger": "human_jump" if decision.target_node else "agent_suggestion",
                            "feedback": decision.feedback,
                        },
                        node_name="__workflow__",
                    )
                    await sse_manager.broadcast(workflow_id, {
                        "event_type": EventType.REROUTE.value,
                        "from_node": paused_by_node_before,
                        "to_node": target,
                        "trigger": "human_jump" if decision.target_node else "agent_suggestion",
                    })

            final_state = await compiled_graph.ainvoke(
                Command(
                    resume=decision.model_dump(mode="json"),
                    update={
                        "human_decision": decision.model_dump(mode="json"),
                        "cached_review_result": cached_review_result,
                    },
                ),
                config,
            )
            await _handle_graph_result(workflow, db, event_logger, workflow_id, final_state)

        except Exception as e:
            await _handle_graph_exception(workflow, db, event_logger, workflow_id, e)

        finally:
            if workflow.status != "paused":
                await sse_manager.close_workflow(workflow_id)


async def recover_workflow(workflow_id: uuid.UUID, engine: AsyncEngine | None = None) -> None:
    """从服务中断中恢复执行。不传 initial_state，LangGraph 从 checkpoint 自动继续。

    与 run_workflow 的区别：
      - 不广播 WORKFLOW_START
      - ainvoke(None, config) 让 LangGraph 加载最近 checkpoint 继续执行
      - 执行前检查最近事件时间，避免对正在运行的工作流误恢复
    """
    session_factory = _session_factory_for_engine(engine)
    async with session_factory() as db:
        workflow = await get_workflow_by_uuid(db, workflow_id)
        if not workflow:
            logger.error(f"工作流 {workflow_id} 不存在")
            return
        if workflow.status != "running":
            logger.warning(f"工作流 {workflow_id} 状态为 {workflow.status}，跳过恢复")
            return

        # 防御性检查：60s 内有事件说明工作流可能正在运行
        last_event_time = await _get_last_event_time(db, workflow_id)
        if last_event_time is not None:
            age = (datetime.now(timezone.utc) - last_event_time.replace(tzinfo=timezone.utc)).total_seconds()
            if age < 60:
                logger.info(f"工作流 {workflow_id} 最近 {age:.0f}s 前有事件，跳过恢复")
                return

        execution_attempt = workflow.execution_attempt
        event_logger = EventLogger(db, workflow_id, execution_attempt)
        checkpointer = await _maybe_get_checkpointer(workflow_id)
        if checkpointer is None:
            return

        try:
            compiled_graph = compile_workflow_graph(
                db, workflow_id, event_logger, execution_attempt, checkpointer,
            )
            config = {"configurable": {"thread_id": _thread_id(workflow_id, execution_attempt)}}

            final_state = await compiled_graph.ainvoke(None, config)
            await _handle_graph_result(workflow, db, event_logger, workflow_id, final_state)

        except Exception as e:
            await _handle_graph_exception(workflow, db, event_logger, workflow_id, e)

        finally:
            if workflow.status != "paused":
                await sse_manager.close_workflow(workflow_id)
