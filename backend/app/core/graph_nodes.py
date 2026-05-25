"""
behavior definitions of nodes.
"""

import json
import uuid
import time
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.collection_agent import CollectionAgent
from app.agents.analysis_agent import AnalysisAgent
from app.agents.report_agent import ReportAgent
from app.agents.review_agent import ReviewAgent
from app.core.node_executor import execute_with_retry, NodeFatalError
from app.services.event_service import EventLogger
from app.db.models.workflow_node_state import WorkflowNodeState
from app.db.models.artifact import Artifact
from app.exceptions import AppException

_collection_agent = CollectionAgent()
_analysis_agent = AnalysisAgent()
_report_agent = ReportAgent()
_review_agent = ReviewAgent()


async def _save_node_state(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    execution_attempt: int,
    node_name: str,
    iteration: int,
    state_snapshot: dict,
    duration_ms: int = 0,
    is_error: bool = False,
    error_message: str | None = None,
) -> WorkflowNodeState:
    """持久化节点执行快照到 WorkflowNodeState 表。"""
    ns = WorkflowNodeState(
        id=uuid.uuid4(),
        workflow_id=workflow_id,
        execution_attempt=execution_attempt,
        node_name=node_name,
        iteration=iteration,
        state_snapshot=_sanitize_for_json(state_snapshot),
        artifact_ids=[],
        duration_ms=duration_ms,
        is_error=is_error,
        error_message=error_message,
    )
    db.add(ns)
    await db.commit()
    return ns


async def _save_artifact(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    execution_attempt: int,
    artifact_type: str,
    title: str,
    content: dict,
    created_by_node: str,
    content_text: str | None = None,
) -> Artifact:
    art = Artifact(
        id=uuid.uuid4(),
        workflow_id=workflow_id,
        execution_attempt=execution_attempt,
        artifact_type=artifact_type,
        title=title,
        content=content,
        content_text=content_text,
        created_by_node=created_by_node,
    )
    db.add(art)
    await db.commit()
    return art


def _sanitize_for_json(state: dict) -> dict:
    """移除不可 JSON 序列化的字段（如 LangChain BaseMessage 对象），并确保所有值可直接写入 JSON 列。

    注意显式跳过 state["messages"]：LangGraph 的消息列表包含 BaseMessage 对象，
    其序列化需 LangChain 的额外逻辑，不适合直接 JSON dump。
    """
    sanitized = {}
    for k, v in state.items():
        if k == "messages":
            continue
        try:
            sanitized[k] = json.loads(json.dumps(v, default=str))
        except (TypeError, ValueError):
            sanitized[k] = str(v)
    return sanitized


async def _execute_node(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    execution_attempt: int,
    node_name: str,
    state: dict,
    event_logger: EventLogger,
    agent_run,
) -> dict:
    """执行节点并保存 state（成功或失败）。

    统一封装：
      - 成功：保存 state_snapshot，正常返回
      - 失败（NodeFatalError）：保存 is_error=True 的节点状态并 re-raise
        使上游 workflow_executor 可以捕获并记录 WORKFLOW_FAILED 事件
    """
    node_logger = event_logger.with_node(node_name, state.get("revision_count", 0))
    start = time.time()
    try:
        result = await execute_with_retry(agent_run, state, node_name, node_logger, workflow_id)
    except NodeFatalError as e:
        duration_ms = int((time.time() - start) * 1000)
        err_msg = str(e.last_error)
        if isinstance(e.last_error, AppException):
            err_msg = e.last_error.message
        await _save_node_state(
            db, workflow_id, execution_attempt, node_name,
            state.get("revision_count", 0), state, duration_ms,
            is_error=True, error_message=err_msg,
        )
        raise
    duration_ms = int((time.time() - start) * 1000)
    merged = {**state, **result}
    await _save_node_state(db, workflow_id, execution_attempt, node_name,
                           state.get("revision_count", 0), merged, duration_ms)
    return result


# closure node definition below
# collection_node
def make_collection_node(db: AsyncSession, workflow_id: uuid.UUID, event_logger: EventLogger, execution_attempt: int):
    async def collection_node(state: dict) -> dict:
        result = await _execute_node(db, workflow_id, execution_attempt, "information_collection", state, event_logger, _collection_agent.run)
        if result.get("raw_data"):
            await _save_artifact(db, workflow_id, execution_attempt, "collection_raw",
                                 "采集原始数据", result["raw_data"], "information_collection")
        return result
    return collection_node


# analysis_node
def make_analysis_node(db: AsyncSession, workflow_id: uuid.UUID, event_logger: EventLogger, execution_attempt: int):
    async def analysis_node(state: dict) -> dict:
        result = await _execute_node(db, workflow_id, execution_attempt, "analysis", state, event_logger, _analysis_agent.run)
        config = state.get("config", {})
        target = config.get("target_product", "") if isinstance(config, dict) else ""
        for art_type, art_key in [
            ("feature_matrix", "feature_matrix"),
            ("pricing_comparison", "pricing_comparison"),
            ("user_sentiment", "user_sentiment"),
            ("swot_analysis", "swot"),
        ]:
            data = result.get(art_key)
            if data is not None:
                await _save_artifact(db, workflow_id, execution_attempt, art_type,
                                     f"{target} {art_type}", data, "analysis")
        return result
    return analysis_node


# report node
def make_report_node(db: AsyncSession, workflow_id: uuid.UUID, event_logger: EventLogger, execution_attempt: int):
    async def report_node(state: dict) -> dict:
        result = await _execute_node(db, workflow_id, execution_attempt, "report_writing", state, event_logger, _report_agent.run)
        report_data = result.get("report")
        if report_data:
            title = report_data.get("title", "竞品分析报告") if isinstance(report_data, dict) else "竞品分析报告"
            markdown = report_data.get("full_markdown", "") if isinstance(report_data, dict) else ""
            await _save_artifact(db, workflow_id, execution_attempt, "report", title,
                                 report_data, "report_writing", content_text=markdown)
        return result
    return report_node


# review node
def make_review_node(db: AsyncSession, workflow_id: uuid.UUID, event_logger: EventLogger, execution_attempt: int):
    async def review_node(state: dict) -> dict:
        result = await _execute_node(db, workflow_id, execution_attempt, "review", state, event_logger, _review_agent.run)
        return result
    return review_node
