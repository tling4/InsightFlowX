from fastapi import APIRouter, Depends, Query
import uuid
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_async_session
from app.dependencies import get_current_user
from app.db.queries.event_queries import get_events, count_events, get_node_states
from app.db.queries.workflow_queries import get_workflow_by_id
from app.services.sse_service import sse_manager
from app.exceptions import WorkflowNotFoundError

router = APIRouter(prefix="/workflows/{workflow_id}", tags=["events"])


@router.get("/events")
async def list_events(
    workflow_id: str,
    node_name: str | None = Query(None),
    event_type: str | None = Query(None),
    execution_attempt: int | None = Query(None, ge=1),
    run_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """分页获取工作流事件列表，支持按 node_name 和 event_type 筛选。"""
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    events = await get_events(db, workflow.id, node_name, event_type, execution_attempt, run_id, limit, offset)
    total = await count_events(db, workflow.id, node_name, event_type, execution_attempt, run_id)
    return {
        "items": [
            {
                "id": str(e.id),
                "node_name": e.node_name,
                "iteration": e.iteration,
                "event_type": e.event_type,
                "seq": e.seq,
                "run_id": str(e.run_id) if e.run_id else None,
                "payload": e.payload,
                "created_at": e.created_at,
            }
            for e in events
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/stream")
async def sse_stream(
    workflow_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """SSE 实时事件流。"""
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    return StreamingResponse(
        sse_manager.stream(workflow.id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/states")
async def list_node_states(
    workflow_id: str,
    execution_attempt: int | None = Query(None, ge=1),
    run_id: uuid.UUID | None = Query(None),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """获取历史节点状态快照列表。"""
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    states = await get_node_states(db, workflow.id, execution_attempt, run_id)
    return [
        {
            "id": str(s.id),
            "node_name": s.node_name,
            "iteration": s.iteration,
            "run_id": str(s.run_id) if s.run_id else None,
            "is_error": s.is_error,
            "duration_ms": s.duration_ms,
            "tokens_input": s.tokens_input,
            "tokens_output": s.tokens_output,
            "model_name": s.model_name,
            "created_at": s.created_at,
        }
        for s in states
    ]
