import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_async_session
from app.dependencies import get_current_user
from app.schemas.auth import UserResponse
from app.schemas.interview import InterviewInput
from app.services.interview_service import (
    stream_interview_response,
    get_message_history
)
from app.services.workflow_service import get_workflow_by_id, confirm_interview

router = APIRouter(prefix="/workflows/{workflow_id}/interview", tags=["interview"])
# api/v1/workflows/{workflow_id}/interview/history

@router.get("/history")
async def get_interview_history(
    workflow_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
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
        raise HTTPException(status_code=404, detail="工作流不存在")

    async def event_generator():
        async for chunk in stream_interview_response(db, uuid.UUID(workflow_id), data.user_message):
            yield f"data: {chunk}\n\n"

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
    if not workflow:
        raise HTTPException(status_code=400, detail="工作流不存在、状态不允许确认或配置未完成")
    return {"workflow_id": str(workflow.id), "status": workflow.status, "config": workflow.config}
