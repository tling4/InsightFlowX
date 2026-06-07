import asyncio
import json
import logging
import uuid
from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_async_session
from app.dependencies import get_current_user
from app.schemas.auth import UserResponse
from app.schemas.interview import InterviewInput
from app.db.queries.workflow_queries import get_workflow_by_id, get_message_history
from app.services.interview_service import stream_interview_response
from app.services.workflow_service import confirm_interview
from app.exceptions import WorkflowNotFoundError

router = APIRouter(prefix="/workflows/{workflow_id}/interview", tags=["interview"])
logger = logging.getLogger(__name__)


@router.get("/history")
async def get_interview_history(
    workflow_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    history = await get_message_history(db, uuid.UUID(workflow_id))
    return [{"role": m.role, "content": m.content, "created_at": m.created_at} for m in history]


@router.post("/stream")
async def interview_stream(
    workflow_id: str,
    data: InterviewInput,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)

    async def event_generator():
        try:
            async for chunk in stream_interview_response(db, uuid.UUID(workflow_id), data.user_message):
                yield f"data: {chunk}\n\n"
        except asyncio.TimeoutError:
            logger.exception("Interview response timed out for workflow %s", workflow_id)
            yield f"event: error\ndata: {json.dumps({'message': 'AI 回复超时，请重试。'}, ensure_ascii=False)}\n\n"
        except Exception:
            logger.exception("Interview response failed for workflow %s", workflow_id)
            yield f"event: error\ndata: {json.dumps({'message': 'AI 回复失败，请重试。'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/confirm")
async def confirm_interview_config(
    workflow_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """确认访谈配置已完成。"""
    workflow = await confirm_interview(db, workflow_id, current_user.id)
    return {"workflow_id": str(workflow.id), "status": workflow.status, "config": workflow.config}
