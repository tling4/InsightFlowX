"""Agent 运行时上下文。

本模块定义了 agent 在执行期间感知到的所有外界接口。
Agent 不直接操作数据库、SSE、事件日志 —— 一切通过 EventSink 和 AgentContext 完成，
实现了 agent 与基础设施的完全解耦。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.schemas.event import EventType
from app.services.event_service import EventLogger
from app.services.sse_service import sse_manager


class EventSink:
    """Agent 对外的事件发射器。

    封装了事件持久化（EventLogger）和实时推送（SSE）的双写逻辑。
    Agent 只需调用 emit / progress / stream_token，无需了解底层实现。

    使用场景：
        - emit:         语义事件（LLM 请求/响应、节点开始/完成、警告等）
        - progress:     用户可读的进度消息（阶段说明，不暴露 LLM token）
        - stream_token: LLM 流式输出的单个 token 块（仅推送 SSE，不写 DB）
    """

    def __init__(self, event_logger: EventLogger, workflow_id: uuid.UUID, node_name: str):
        self.event_logger = event_logger
        self.workflow_id = workflow_id
        self.node_name = node_name

    async def emit(self, event_type: EventType, payload: dict | None = None) -> None:
        """发送语义事件：入库 + SSE 广播。

        Args:
            event_type: 事件类型枚举（NODE_PROGRESS / LLM_REQUEST / REROUTE 等）
            payload:   事件携带的数据，会存入 DB 并推送给前端
        """
        event = await self.event_logger.log(event_type=event_type, payload=payload or {})
        await sse_manager.broadcast(self.workflow_id, {
            "event_type": event_type.value,
            "node_name": event.node_name or self.node_name,
            "seq": event.seq,
            "payload": payload or {},
            "created_at": str(event.created_at),
        })

    async def progress(self, *, stage: str, message: str, level: str = "info") -> None:
        """发送用户可见的节点进度消息。

        Args:
            stage:   当前阶段标识（如 "searching", "analyzing", "writing"）
            message: 人类可读的进度描述
            level:   日志级别（"info" / "warn" / "error"），默认 "info"
        """
        await self.emit(
            EventType.NODE_PROGRESS,
            {
                "stage": stage,
                "message": message,
                "level": level,
            },
        )

    async def stream_token(self, token: str) -> None:
        """将 LLM 流式输出的单个 token 块推送给 SSE 订阅者。

        注意：token 粒度太细，这里不写数据库，仅做实时推送。
        前端通过 event_type="llm_stream" 区分此事件。
        """
        await sse_manager.broadcast(self.workflow_id, {
            "event_type": EventType.LLM_STREAM.value,
            "node_name": self.node_name,
            "content": token,
        })


@dataclass(frozen=True)
class AgentContext:
    """注入到每次 agent 调用的运行时上下文。

    包含执行标识、事件发射器以及预留的 LLM / 工具绑定。
    NodeRunner 在每次调用 spec.agent.run() 前构造此对象，
    agent 通过 ctx.events 发送事件、通过 ctx.llm 调用模型。

    Attributes:
        workflow_id: 所属工作流 UUID
        run_id:      本次执行实例 UUID
        node_id:     节点名称（对应 NodeSpec.id）
        iteration:   当前修订次数（从 control.revision_count 计算）
        events:      Agent 对外的事件发射器
        llm:         预留的 LLM 客户端（ChatOpenAI 等）
        tools:       预留的工具绑定列表
    """

    workflow_id: uuid.UUID
    run_id: uuid.UUID
    node_id: str
    iteration: int
    events: EventSink
    llm: Any = None
    tools: Any = None
