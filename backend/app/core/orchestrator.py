import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from langgraph.graph import StateGraph, END
from app.schemas.workflow_state import WorkflowState
from app.services.event_service import EventLogger
from app.core.graph_nodes import (
    make_collection_node,
    make_analysis_node,
    make_report_node,
    make_review_node,
)


def _review_router(state: dict) -> str:
    """审查节点后的条件路由。"""
    review = state.get("review_result")
    if review is None:
        return "done"

    passed = review.get("passed", True) if isinstance(review, dict) else True
    if passed:
        return "done"

    revision_count = state.get("revision_count", 0)
    max_revisions = state.get("max_revisions", 3)
    if revision_count >= max_revisions:
        return "done"

    target = review.get("target_node", "analysis") if isinstance(review, dict) else "analysis"
    if target in ("information_collection", "analysis", "report_writing"):
        return target
    return "analysis"


def compile_workflow_graph(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    event_logger: EventLogger,
):
    """为指定工作流编译 LangGraph StateGraph。"""
    graph = StateGraph(WorkflowState)

    graph.add_node("information_collection", make_collection_node(db, workflow_id, event_logger))
    graph.add_node("analysis", make_analysis_node(db, workflow_id, event_logger))
    graph.add_node("report_writing", make_report_node(db, workflow_id, event_logger))
    graph.add_node("review", make_review_node(db, workflow_id, event_logger))

    graph.set_entry_point("information_collection")

    graph.add_edge("information_collection", "analysis")
    graph.add_edge("analysis", "report_writing")
    graph.add_edge("report_writing", "review")

    graph.add_conditional_edges(
        "review",
        _review_router,
        {
            "done": END,
            "information_collection": "information_collection",
            "analysis": "analysis",
            "report_writing": "report_writing",
        },
    )

    return graph.compile()
