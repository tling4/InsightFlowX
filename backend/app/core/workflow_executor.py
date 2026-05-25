import uuid
import logging
from datetime import datetime, timezone
from app.db.session import async_session_factory
from app.db.queries.workflow_queries import get_workflow_by_uuid
from app.core.orchestrator import compile_workflow_graph
from app.services.event_service import EventLogger
from app.services.sse_service import sse_manager
from app.schemas.event import EventType
from app.exceptions import AppException
from app.core.node_executor import NodeFatalError

logger = logging.getLogger(__name__)


def _extract_error_info(e: Exception) -> tuple[str, str, dict | None]:
    """从异常中提取结构化错误信息。

    优先解包 NodeFatalError → AppException 以获取业务 error_code；
    兜底返回通用 EXECUTION_ERROR 和异常消息截断。
    """
    if isinstance(e, NodeFatalError) and isinstance(e.last_error, AppException):
        app_err = e.last_error
        return app_err.error_code, app_err.message, app_err.details
    if isinstance(e, AppException):
        return e.error_code, e.message, e.details
    return "EXECUTION_ERROR", str(e)[:1000], None


async def run_workflow(workflow_id: uuid.UUID) -> None:
    """BackgroundTasks 入口，运行完整 DAG。使用独立 DB session。

    生命周期：
      1. 校验工作流状态为 running
      2. 编译 LangGraph，注入 initial state
      3. ainvoke 执行，成功后标记 completed
      4. 失败时 rollback → status = failed → 记录结构化事件
    """
    async with async_session_factory() as db:
        workflow = await get_workflow_by_uuid(db, workflow_id)
        if not workflow:
            logger.error(f"工作流 {workflow_id} 不存在")
            return
        if workflow.status != "running":
            logger.warning(f"工作流 {workflow_id} 状态为 {workflow.status}，跳过执行")
            return

        execution_attempt = workflow.execution_attempt
        event_logger = EventLogger(db, workflow_id, execution_attempt)

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
            compiled_graph = compile_workflow_graph(db, workflow_id, event_logger, execution_attempt)

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

            final_state = await compiled_graph.ainvoke(initial_state)

            workflow.status = "completed"
            workflow.current_phase = "done"
            workflow.revision_count = final_state.get("revision_count", 0)
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

        except Exception as e:
            logger.exception(f"工作流 {workflow_id} 执行失败: {e}")
            try:
                # 节点内部各自 commit，当前 session 无未提交变更，无需 rollback。
                # 回滚由 execution_attempt 机制在逻辑层面完成：失败 attempt 的数据留存
                # 供调试，后续 attempt 写入新 execution_attempt 号，互不干扰。
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

        finally:
            await sse_manager.close_workflow(workflow_id)
