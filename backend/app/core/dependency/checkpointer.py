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

import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_saver: Any | None = None
_conn: Any | None = None


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
    _conn = await psycopg.AsyncConnection.connect(
        settings.DATABASE_URL_SYNC,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    _saver = AsyncPostgresSaver(conn=_conn)
    await _saver.setup()
    logger.info("Postgres checkpointer initialized")


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
