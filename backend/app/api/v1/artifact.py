import uuid as _uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_async_session
from app.dependencies import get_current_user
from app.db.models.artifact import Artifact
from app.db.models.workflow import Workflow
from app.services.workflow_service import get_workflow_by_id

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
        raise HTTPException(status_code=404, detail="工作流不存在")
    result = await db.execute(
        select(Artifact).where(Artifact.workflow_id == workflow.id).order_by(Artifact.created_at)
    )
    artifacts = result.scalars().all()
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
    result = await db.execute(select(Artifact).where(Artifact.id == artifact_id))
    artifact = result.scalar_one_or_none()
    if not artifact:
        raise HTTPException(status_code=404, detail="产物不存在")
    wf_result = await db.execute(
        select(Workflow).where(Workflow.id == artifact.workflow_id, Workflow.owner_id == current_user.id)
    )
    if not wf_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="产物不存在")
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
    result = await db.execute(select(Artifact).where(Artifact.id == artifact_id))
    artifact = result.scalar_one_or_none()
    if not artifact:
        raise HTTPException(status_code=404, detail="产物不存在")
    wf_result = await db.execute(
        select(Workflow).where(Workflow.id == artifact.workflow_id, Workflow.owner_id == current_user.id)
    )
    if not wf_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="产物不存在")
    markdown = artifact.content_text or ""
    if not markdown and artifact.artifact_type == "report":
        markdown = artifact.content.get("full_markdown", "") if isinstance(artifact.content, dict) else ""
    return PlainTextResponse(
        content=markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{artifact.title}.md"'},
    )
