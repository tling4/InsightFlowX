import asyncio
import logging
from app.services.event_service import EventLogger
from app.schemas.event import EventType
from app.exceptions import AppException

logger = logging.getLogger(__name__)

NODE_TIMEOUT = 300
MAX_RETRIES = 3


class NodeFatalError(Exception):
    """节点在耗尽所有重试次数后仍然失败时抛出，携带最后一次异常供上层解包。"""
    def __init__(self, node: str, attempts: int, last_error: Exception):
        self.node = node
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"节点 '{node}' 在 {attempts} 次重试后仍然失败: {last_error}")


async def execute_with_retry(
    node_fn,
    state: dict,
    node_name: str,
    event_logger: EventLogger,
    workflow_id,
) -> dict:
    """带指数退避重试的节点执行器。

    重试策略：
      - 单次超时 300s (NODE_TIMEOUT)
      - 最多 3 次 (MAX_RETRIES)
      - 第 n 次重试前等待 2^n 秒
      - 每次失败记录 NODE_ERROR 事件（携带业务 error_code）
      - 所有重试耗尽后抛出 NodeFatalError
    """
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = await asyncio.wait_for(
                node_fn(state, event_logger, workflow_id),
                timeout=NODE_TIMEOUT,
            )
            return result
        except Exception as e:
            last_error = e
            logger.warning(f"节点 {node_name} 第 {attempt} 次执行失败: {e}")
            inner_code = e.error_code if isinstance(e, AppException) else type(e).__name__
            await event_logger.log(
                event_type=EventType.NODE_ERROR,
                payload={
                    "error_code": inner_code,
                    "error_message": str(e)[:500],
                    "retry_count": attempt,
                    "max_retries": MAX_RETRIES,
                },
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)
                continue
            break

    raise NodeFatalError(node=node_name, attempts=MAX_RETRIES, last_error=last_error)
