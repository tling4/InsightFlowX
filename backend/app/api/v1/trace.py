from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_async_session
from app.dependencies import get_current_user
from app.db.models.trace_link import TraceLink
from app.db.models.artifact import Artifact
from app.services.workflow_service import get_workflow_by_id

router = APIRouter(prefix="/workflows/{workflow_id}", tags=["trace"])


@router.get("/trace")
async def list_trace_links(
    workflow_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """获取工作流的溯源链接列表。"""
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    art_result = await db.execute(
        select(Artifact.id).where(Artifact.workflow_id == workflow.id)
    )
    artifact_ids = [row[0] for row in art_result.all()]
    if not artifact_ids:
        return []
    result = await db.execute(
        select(TraceLink).where(TraceLink.artifact_id.in_(artifact_ids)).order_by(TraceLink.created_at)
    )
    links = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "artifact_id": str(t.artifact_id),
            "section_path": t.section_path,
            "claim_text": t.claim_text,
            "source_url": t.source_url,
            "source_title": t.source_title,
            "source_type": t.source_type,
            "confidence": t.confidence,
            "is_verified": t.is_verified,
            "created_at": t.created_at,
        }
        for t in links
    ]
