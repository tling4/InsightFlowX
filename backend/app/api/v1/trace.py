from fastapi import APIRouter, Depends
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_async_session
from app.dependencies import get_current_user
from app.db.queries.workflow_queries import get_workflow_by_id
from app.db.queries.artifact_queries import get_artifact_ids_by_workflow, get_trace_links
from app.exceptions import WorkflowNotFoundError

router = APIRouter(prefix="/workflows/{workflow_id}", tags=["trace"])


@router.get("/trace")
async def list_trace_links(
    workflow_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
    execution_attempt: int | None = None,
    run_id: uuid.UUID | None = None,
):
    """获取工作流的溯源链接列表。"""
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    artifact_ids = await get_artifact_ids_by_workflow(db, workflow.id, execution_attempt, run_id)
    if not artifact_ids:
        return []
    links = await get_trace_links(db, artifact_ids)
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
