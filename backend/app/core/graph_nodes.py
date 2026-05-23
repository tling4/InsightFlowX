import json
import uuid
import time
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.collection_agent import CollectionAgent
from app.agents.analysis_agent import AnalysisAgent
from app.agents.report_agent import ReportAgent
from app.agents.review_agent import ReviewAgent
from app.core.node_executor import execute_with_retry
from app.services.event_service import EventLogger
from app.db.models.workflow_node_state import WorkflowNodeState
from app.db.models.artifact import Artifact

_collection_agent = CollectionAgent()
_analysis_agent = AnalysisAgent()
_report_agent = ReportAgent()
_review_agent = ReviewAgent()


async def _save_node_state(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    node_name: str,
    iteration: int,
    state_snapshot: dict,
    duration_ms: int = 0,
    is_error: bool = False,
    error_message: str | None = None,
) -> WorkflowNodeState:
    ns = WorkflowNodeState(
        id=uuid.uuid4(),
        workflow_id=workflow_id,
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
    artifact_type: str,
    title: str,
    content: dict,
    created_by_node: str,
    content_text: str | None = None,
) -> Artifact:
    art = Artifact(
        id=uuid.uuid4(),
        workflow_id=workflow_id,
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
    """移除不可 JSON 序列化的字段（如 LangChain BaseMessage 对象），并确保所有值可直接写入 JSON 列。"""
    sanitized = {}
    for k, v in state.items():
        if k == "messages":
            continue
        try:
            sanitized[k] = json.loads(json.dumps(v, default=str))
        except (TypeError, ValueError):
            sanitized[k] = str(v)
    return sanitized


def make_collection_node(db: AsyncSession, workflow_id: uuid.UUID, event_logger: EventLogger):
    async def collection_node(state: dict) -> dict:
        node_logger = event_logger.with_node("information_collection", state.get("revision_count", 0))
        start = time.time()
        result = await execute_with_retry(
            _collection_agent.run, state, "information_collection", node_logger, workflow_id,
        )
        duration_ms = int((time.time() - start) * 1000)
        merged = {**state, **result}
        await _save_node_state(db, workflow_id, "information_collection",
                               state.get("revision_count", 0), merged, duration_ms)
        if result.get("raw_data"):
            await _save_artifact(db, workflow_id, "collection_raw",
                                 "采集原始数据", result["raw_data"], "information_collection")
        return result
    return collection_node


def make_analysis_node(db: AsyncSession, workflow_id: uuid.UUID, event_logger: EventLogger):
    async def analysis_node(state: dict) -> dict:
        node_logger = event_logger.with_node("analysis", state.get("revision_count", 0))
        start = time.time()
        result = await execute_with_retry(
            _analysis_agent.run, state, "analysis", node_logger, workflow_id,
        )
        duration_ms = int((time.time() - start) * 1000)
        merged = {**state, **result}
        await _save_node_state(db, workflow_id, "analysis",
                               state.get("revision_count", 0), merged, duration_ms)
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
                await _save_artifact(db, workflow_id, art_type,
                                     f"{target} {art_type}", data, "analysis")
        return result
    return analysis_node


def make_report_node(db: AsyncSession, workflow_id: uuid.UUID, event_logger: EventLogger):
    async def report_node(state: dict) -> dict:
        node_logger = event_logger.with_node("report_writing", state.get("revision_count", 0))
        start = time.time()
        result = await execute_with_retry(
            _report_agent.run, state, "report_writing", node_logger, workflow_id,
        )
        duration_ms = int((time.time() - start) * 1000)
        merged = {**state, **result}
        await _save_node_state(db, workflow_id, "report_writing",
                               state.get("revision_count", 0), merged, duration_ms)
        report_data = result.get("report")
        if report_data:
            title = report_data.get("title", "竞品分析报告") if isinstance(report_data, dict) else "竞品分析报告"
            markdown = report_data.get("full_markdown", "") if isinstance(report_data, dict) else ""
            await _save_artifact(db, workflow_id, "report", title,
                                 report_data, "report_writing", content_text=markdown)
        return result
    return report_node


def make_review_node(db: AsyncSession, workflow_id: uuid.UUID, event_logger: EventLogger):
    async def review_node(state: dict) -> dict:
        node_logger = event_logger.with_node("review", state.get("revision_count", 0))
        start = time.time()
        result = await execute_with_retry(
            _review_agent.run, state, "review", node_logger, workflow_id,
        )
        duration_ms = int((time.time() - start) * 1000)
        merged = {**state, **result}
        await _save_node_state(db, workflow_id, "review",
                               state.get("revision_count", 0), merged, duration_ms)
        return result
    return review_node
