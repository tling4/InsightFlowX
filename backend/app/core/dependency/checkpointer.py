"""LangGraph Postgres 检查点管理。

通过 AsyncPostgresSaver 将 StateGraph 的执行状态持久化到 PostgreSQL，
支持工作流的中断恢复（resume）和僵尸恢复（recover）。

生命周期：
    app 启动时调用 init_checkpointer()   → 建立连接 + setup 表结构
    app 关闭时调用 shutdown_checkpointer() → 关闭连接
    运行时调用 get_checkpointer()         → 返回已初始化的 saver 实例

使用方式：
    checkpointer = await get_checkpointer()
    runtime = GraphRuntime(..., checkpointer=checkpointer)
"""

import asyncio
import logging
import platform
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_saver: Any | None = None
_conn: Any | None = None


def _is_proactor_loop() -> bool:
    """检测当前运行的事件循环是否为 Windows ProactorEventLoop。"""
    if platform.system() != "Windows":
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    return type(loop).__name__ == "ProactorEventLoop"


async def init_checkpointer() -> None:
    """初始化 Postgres 检查点保存器。

    使用 psycopg 异步连接 + dict_row 行工厂，
    调用 saver.setup() 自动创建 langgraph checkpoint 所需的表。

    Raises:
        RuntimeError: 如果未安装 psycopg
    """
    global _saver, _conn

    settings = get_settings()
    if not (
        settings.DATABASE_URL_SYNC.startswith("postgresql://")
        or settings.DATABASE_URL_SYNC.startswith("postgres://")
    ):
        _saver = None
        _conn = None
        logger.info("Postgres checkpointer disabled (DATABASE_URL_SYNC is not PostgreSQL)")
        return
    try:
        import psycopg
    except ModuleNotFoundError as exc:
        raise RuntimeError("psycopg is required to initialize the Postgres checkpointer") from exc

    try:
        from langgraph.checkpoint.postgres import dict_row
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except Exception as exc:
        raise RuntimeError("langgraph-checkpoint-postgres is required to initialize the Postgres checkpointer") from exc

    if _is_proactor_loop():
        logger.info("Windows ProactorEventLoop detected, connecting psycopg in dedicated SelectorEventLoop thread")
        _conn, _saver = await _connect_in_selector_thread(settings, psycopg, dict_row, AsyncPostgresSaver)
    else:
        _conn = await psycopg.AsyncConnection.connect(
            settings.DATABASE_URL_SYNC,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        _saver = AsyncPostgresSaver(conn=_conn)
        await _saver.setup()
    logger.info("Postgres checkpointer initialized")


async def _connect_in_selector_thread(
    settings, psycopg, dict_row, AsyncPostgresSaver
) -> tuple[Any, Any]:
    """在独立线程中用 SelectorEventLoop 建立 psycopg 连接。

    uvicorn 在 Windows 非 reload 模式下硬编码使用 ProactorEventLoop
    （见 uvicorn/loops/asyncio.py:asyncio_loop_factory），
    而 psycopg 的 AsyncConnection.connect() 要求 SelectorEventLoop。
    此函数将连接握手隔离在专用 SelectorEventLoop 线程中执行，
    建立后的 AsyncConnection 可在任意事件循环中使用。
    """
    result: dict[str, Any] = {}
    error: Exception | None = None

    def _run():
        nonlocal error
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def _setup():
                conn = await psycopg.AsyncConnection.connect(
                    settings.DATABASE_URL_SYNC,
                    autocommit=True,
                    prepare_threshold=0,
                    row_factory=dict_row,
                )
                saver = AsyncPostgresSaver(conn=conn)
                await saver.setup()
                return conn, saver

            conn, saver = loop.run_until_complete(_setup())
            result["conn"] = conn
            result["saver"] = saver
        except Exception as e:
            error = e

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        await loop.run_in_executor(pool, _run)

    if error:
        raise error
    return result["conn"], result["saver"]


async def get_checkpointer() -> Any:
    """获取已初始化的检查点保存器实例。

    Returns:
        全局 AsyncPostgresSaver 实例

    Raises:
        RuntimeError: 如果 checkpointer 尚未初始化
    """
    if _saver is None:
        raise RuntimeError("Checkpointer not initialized")
    return _saver


async def shutdown_checkpointer() -> None:
    """关闭检查点数据库连接。

    应在 app 关闭时调用，释放 psycopg 连接资源。
    """
    global _saver, _conn
    if _conn is not None:
        await _conn.close()
        _saver = None
        _conn = None
        logger.info("Postgres checkpointer connection closed")
