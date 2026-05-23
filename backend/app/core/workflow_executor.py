import uuid
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from app.db.session import async_session_factory
from app.db.models.workflow import Workflow
from app.core.orchestrator import compile_workflow_graph
from app.services.event_service import EventLogger
from app.services.sse_service import sse_manager
from app.schemas.event import EventType

logger = logging.getLogger(__name__)


async def run_workflow(workflow_id: uuid.UUID) -> None:
    """BackgroundTasks 入口，运行完整 DAG。使用独立 DB session。"""
    async with async_session_factory() as db:
        result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
        workflow = result.scalar_one_or_none()
        if not workflow:
            logger.error(f"工作流 {workflow_id} 不存在")
            return
        if workflow.status != "running":
            logger.warning(f"工作流 {workflow_id} 状态为 {workflow.status}，跳过执行")
            return

        event_logger = EventLogger(db, workflow_id)

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
            compiled_graph = compile_workflow_graph(db, workflow_id, event_logger)

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
                await db.rollback()
                workflow.status = "failed"
                workflow.error_message = str(e)[:1000]
                await db.commit()

                await event_logger.log(
                    event_type=EventType.WORKFLOW_FAILED,
                    payload={"error_message": str(e)[:500]},
                    node_name="__workflow__",
                )
                await sse_manager.broadcast(workflow_id, {
                    "event_type": EventType.WORKFLOW_FAILED.value,
                    "error_message": str(e)[:200],
                })
            except Exception:
                logger.exception(f"工作流 {workflow_id} 错误处理也失败")

        finally:
            await sse_manager.close_workflow(workflow_id)
