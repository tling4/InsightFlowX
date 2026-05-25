"""
langgraph stategraph building and dynamic DAG routing.
"""

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
    """审查节点后的条件路由：通过则结束，未通过且在重试上限内则回退到指定节点重做。"""
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
    execution_attempt: int,
):
    """编译 LangGraph StateGraph。

    工作流 DAG 结构：
      information_collection → analysis → report_writing → review
                                                          │
                                          (不通过, revision < max) ───→ analysis (或指定节点)
                                          (通过 或 revision >= max) ──→ END
    """
    graph = StateGraph(WorkflowState)

    graph.add_node("information_collection", make_collection_node(db, workflow_id, event_logger, execution_attempt))
    graph.add_node("analysis", make_analysis_node(db, workflow_id, event_logger, execution_attempt))
    graph.add_node("report_writing", make_report_node(db, workflow_id, event_logger, execution_attempt))
    graph.add_node("review", make_review_node(db, workflow_id, event_logger, execution_attempt))

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
