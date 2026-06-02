"""
langgraph stategraph building and dynamic DAG routing.
"""

import uuid

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.graph_nodes import (
    make_analysis_node,
    make_collection_node,
    make_report_node,
    make_review_node,
)
from app.schemas.workflow_state import WorkflowState
from app.services.event_service import EventLogger


REROUTE_TARGETS = ("information_collection", "analysis", "report_writing")


def make_pause_router(current_node: str, default_next: str):
    """Create the conditional router used after each node.

    The router must only return hashable route labels. Returning a Command here
    would make LangGraph hash the Command object inside the conditional branch
    machinery, which fails because Command may contain dict payloads.
    """

    def _router(state: dict) -> str:
        # Review nodes can carry an explicit reroute target after resume.
        if current_node == "review":
            revision_count = state.get("revision_count", 0)
            max_revisions = state.get("max_revisions", 3)

            human_decision = state.get("human_decision") or {}
            if human_decision.get("action") == "jump":
                target = human_decision.get("target_node")
                if target in REROUTE_TARGETS and revision_count < max_revisions:
                    return target

            reroute_target = state.get("review_reroute_target")
            if reroute_target in REROUTE_TARGETS and revision_count < max_revisions:
                return reroute_target

            if not state.get("review_result_consumed"):
                review = state.get("review_result")
                if isinstance(review, dict):
                    target = review.get("target_node")
                    if target in REROUTE_TARGETS and revision_count < max_revisions:
                        return target

        return default_next

    return _router


def compile_workflow_graph(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    event_logger: EventLogger,
    execution_attempt: int,
    checkpointer: PostgresSaver | None = None,
):
    """Compile the LangGraph StateGraph for the workflow."""

    graph = StateGraph(WorkflowState)

    graph.add_node("information_collection", make_collection_node(db, workflow_id, event_logger, execution_attempt))
    graph.add_node("analysis", make_analysis_node(db, workflow_id, event_logger, execution_attempt))
    graph.add_node("report_writing", make_report_node(db, workflow_id, event_logger, execution_attempt))
    graph.add_node("review", make_review_node(db, workflow_id, event_logger, execution_attempt))

    graph.set_entry_point("information_collection")

    node_edges = [
        ("information_collection", "analysis"),
        ("analysis", "report_writing"),
        ("report_writing", "review"),
        ("review", "done"),
    ]
    for node_name, default_next in node_edges:
        mapping = {t: t for t in REROUTE_TARGETS}
        if default_next == "done":
            mapping["done"] = END
        else:
            mapping[default_next] = default_next
        graph.add_conditional_edges(node_name, make_pause_router(node_name, default_next), mapping)

    return graph.compile(checkpointer=checkpointer)
