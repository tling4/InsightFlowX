from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.workflow import router as workflow_router
from app.api.v1.interview import router as interview_router
from app.api.v1.event import router as event_router
from app.api.v1.artifact import router as artifact_router
from app.api.v1.trace import router as trace_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(auth_router)
v1_router.include_router(workflow_router)
v1_router.include_router(interview_router)
v1_router.include_router(event_router)
v1_router.include_router(artifact_router)
v1_router.include_router(trace_router)
