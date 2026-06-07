import asyncio
import logging
import platform
from contextlib import asynccontextmanager

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ── LangSmith 早启动：必须在任何 langchain 模块导入前执行 ──
import app.core.dependency.langsmith  # noqa: F401  side-effect: 注入 os.environ

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.v1.router import v1_router
from app.db.base import Base
from app.db.session import engine
from app.core.dependency.checkpointer import init_checkpointer, shutdown_checkpointer
from app.exceptions import AppException

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_checkpointer()
    yield
    await shutdown_checkpointer()
    await engine.dispose()


app = FastAPI(title="DAGents-InsightFlow", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """全局业务异常处理器：将 AppException 及其子类自动转为统一 JSON 响应。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error_code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """全局兜底异常处理器：未被 AppException 捕获的异常返回 500 + INTERNAL_ERROR。"""
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_ERROR",
            "message": "服务器内部错误",
            "details": None,
        },
    )


app.include_router(v1_router)
