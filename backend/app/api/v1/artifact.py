import uuid as _uuid
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_async_session
from app.dependencies import get_current_user
from app.db.queries.workflow_queries import get_workflow_by_id
from app.db.queries.artifact_queries import get_workflow_artifacts, get_artifact_by_id
from app.exceptions import WorkflowNotFoundError, ArtifactNotFoundError

router = APIRouter(tags=["artifacts"])


@router.get("/workflows/{workflow_id}/artifacts")
async def list_artifacts(
    workflow_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """获取工作流产物列表。"""
    workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
    if not workflow:
        raise WorkflowNotFoundError(workflow_id)
    artifacts = await get_workflow_artifacts(db, workflow.id)
    return [
        {
            "id": str(a.id),
            "artifact_type": a.artifact_type,
            "title": a.title,
            "created_by_node": a.created_by_node,
            "format_version": a.format_version,
            "created_at": a.created_at,
        }
        for a in artifacts
    ]


@router.get("/artifacts/{artifact_id}")
async def get_artifact_detail(
    artifact_id: _uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """获取单个产物详情（含 content JSON）。"""
    artifact = await get_artifact_by_id(db, artifact_id)
    if not artifact:
        raise ArtifactNotFoundError(str(artifact_id))
    ownership_check = await get_workflow_by_id(db, artifact.workflow_id, current_user.id)
    if not ownership_check:
        raise WorkflowNotFoundError(str(artifact.workflow_id))
    return {
        "id": str(artifact.id),
        "artifact_type": artifact.artifact_type,
        "title": artifact.title,
        "content": artifact.content,
        "content_text": artifact.content_text,
        "created_by_node": artifact.created_by_node,
        "format_version": artifact.format_version,
        "created_at": artifact.created_at,
    }


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(
    artifact_id: _uuid.UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    """下载产物 Markdown 文件。"""
    artifact = await get_artifact_by_id(db, artifact_id)
    if not artifact:
        raise ArtifactNotFoundError(str(artifact_id))
    ownership_check = await get_workflow_by_id(db, artifact.workflow_id, current_user.id)
    if not ownership_check:
        raise WorkflowNotFoundError(str(artifact.workflow_id))
    markdown = artifact.content_text or ""
    if not markdown and artifact.artifact_type == "report":
        markdown = artifact.content.get("full_markdown", "") if isinstance(artifact.content, dict) else ""
    return PlainTextResponse(
        content=markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{artifact.title}.md"'},
    )
