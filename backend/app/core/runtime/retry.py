"""节点执行重试机制。

提供带指数退避的重试执行器 execute_with_retry 和
专用异常 NodeFatalError（重试耗尽时抛出）。

使用方式：
    result = await execute_with_retry(
        node_fn,          # async callable(state) -> dict
        state,            # 输入状态
        node_name,        # 节点名（用于日志）
        event_logger,     # EventLogger 实例（记录 NODE_ERROR 事件）
        retry_policy,     # RetryPolicy 配置（可选，默认 3 次 / 300s 超时）
    )

当 graph 调用 interrupt() 时，langgraph 会抛出 GraphInterrupt ——
此异常不参与重试，直接向上传播。
"""

import asyncio
import logging

from langgraph.errors import GraphInterrupt

from app.exceptions import AppException
from app.schemas.event import EventType

logger = logging.getLogger(__name__)

NODE_TIMEOUT = 300
MAX_RETRIES = 3


class NodeFatalError(Exception):
    """节点在耗尽所有重试次数后仍然失败时抛出。

    携带最后一次异常供上层解包（NodeRunner 用于保存错误快照，
    workflow_executor 用于提取 error_code / message / details）。

    Attributes:
        node:       节点名
        attempts:   已尝试次数
        last_error: 最后一次捕获的异常对象

    Properties（统一从 last_error 提取）:
        error_code:     错误码字符串（AppException.error_code 或异常类名）
        error_message:  错误消息
        error_details:  附加详情（AppException.details 或 None）
        error_info:     三元组 (code, message, details)
    """

    def __init__(self, node: str, attempts: int, last_error: Exception):
        self.node = node
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"节点 '{node}' 在 {attempts} 次重试后仍然失败: {last_error}")

    @property
    def error_code(self) -> str:
        """从 last_error 提取错误码。

        AppException → 其 error_code，其他异常 → 类型名。
        """
        if isinstance(self.last_error, AppException):
            return self.last_error.error_code
        return type(self.last_error).__name__

    @property
    def error_message(self) -> str:
        """从 last_error 提取人类可读的错误消息。

        AppException → 其 message，其他异常 → str(last_error)。
        """
        if isinstance(self.last_error, AppException):
            return self.last_error.message
        return str(self.last_error)

    @property
    def error_details(self) -> dict | None:
        """从 last_error 提取附加详情。

        AppException → 其 details，其他异常 → None。
        """
        if isinstance(self.last_error, AppException):
            return self.last_error.details
        return None

    @property
    def error_info(self) -> tuple[str, str, dict | None]:
        """三元组 (error_code, error_message, error_details)。

        供上层统一提取错误信息，消除各处的 isinstance 解包重复。
        """
        return self.error_code, self.error_message, self.error_details


async def execute_with_retry(
    node_fn,
    state: dict,
    node_name: str,
    event_logger,
    retry_policy=None,
) -> dict:
    """带指数退避的节点执行器。

    重试策略:
        - 单次超时: retry_policy.timeout_sec 或 NODE_TIMEOUT (300s)
        - 最大重试: retry_policy.max_attempts 或 MAX_RETRIES (3)
        - 退避等待: 第 n 次失败后等待 backoff_base^n 秒（默认 2^n）
        - 每次失败记录 NODE_ERROR 事件（携带业务 error_code）
        - 全部重试耗尽后抛出 NodeFatalError

    Args:
        node_fn:      async callable(state) -> dict，单次 agent 调用
        state:        传入 node_fn 的当前状态
        node_name:    节点标识（日志 + 异常）
        event_logger: EventLogger 实例
        retry_policy: RetryPolicy 对象（可选，未提供时使用默认值）

    Returns:
        dict: node_fn 的返回值

    Raises:
        NodeFatalError: 全部重试耗尽后仍失败
        GraphInterrupt: 直接传播，不参与重试
    """
    max_retries = getattr(retry_policy, "max_attempts", MAX_RETRIES)
    timeout = getattr(retry_policy, "timeout_sec", NODE_TIMEOUT)
    backoff_base = getattr(retry_policy, "backoff_base_sec", 2)

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            result = await asyncio.wait_for(node_fn(state), timeout=timeout)
            return result
        except GraphInterrupt:
            raise
        except Exception as e:
            last_error = e
            logger.warning("节点 %s 第 %d 次执行失败: %s", node_name, attempt, e)
            inner_code = e.error_code if isinstance(e, AppException) else type(e).__name__
            await event_logger.log(
                event_type=EventType.NODE_ERROR,
                payload={
                    "error_code": inner_code,
                    "error_message": str(e)[:500],
                    "retry_count": attempt,
                    "max_retries": max_retries,
                },
            )
            if attempt < max_retries:
                await asyncio.sleep(backoff_base**attempt)
                continue
            break

    raise NodeFatalError(node=node_name, attempts=max_retries, last_error=last_error)
