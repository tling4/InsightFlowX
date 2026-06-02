import uuid
from typing import Any, TypeVar

from pydantic import BaseModel

from app.agents.agent_utils import invoke_json_model
from app.services.event_service import EventLogger
from app.services.sse_service import sse_manager
from app.schemas.event import EventType

T = TypeVar("T", bound=BaseModel)


class BaseAgent:
    """DAG Agent 基类。

    提供三个可复用钩子：
    - log_and_broadcast: 事件持久化 + SSE 实时推送（双写）
    - stream_llm_token:   LLM 流式 token 逐块推向前端
    - invoke_llm:         封装 LLM 调用 + 流式广播 + 结构化解码的完整流程
    """

    node_name: str = ""

    # ── 事件 / SSE ──────────────────────────────────────────────

    async def log_and_broadcast(
        self,
        event_logger: EventLogger,
        event_type: EventType,
        payload: dict,
        workflow_id: uuid.UUID,
    ) -> None:
        """双写：持久化到数据库 + 广播 SSE。

        持久化保证历史复盘有据可查，SSE 保证前端实时看到节点进度。
        两者写入同一个 payload，避免信息不一致。
        """
        event = await event_logger.log(event_type=event_type, payload=payload)
        await sse_manager.broadcast(workflow_id, {
            "event_type": event_type.value,
            "node_name": event.node_name,
            "seq": event.seq,
            "payload": payload,
            "created_at": str(event.created_at),
        })

    async def emit_progress(
        self,
        event_logger: EventLogger,
        workflow_id: uuid.UUID,
        *,
        stage: str,
        message: str,
        level: str = "info",
    ) -> None:
        """发送用户可见的节点过程说明，不暴露模型原始 token。"""
        await self.log_and_broadcast(
            event_logger,
            EventType.NODE_PROGRESS,
            {
                "stage": stage,
                "message": message,
                "level": level,
            },
            workflow_id,
        )

    async def stream_llm_token(self, workflow_id: uuid.UUID, token: str) -> None:
        """向 SSE 订阅者广播 LLM 流式输出的单个 token 块。

        与 log_and_broadcast 不同，这里不写数据库 — token 粒度太细，
        写入会产生大量 IO。前端通过 event_type="llm_stream" 区分。
        """
        await sse_manager.broadcast(workflow_id, {
            "event_type": "llm_stream",
            "node_name": self.node_name,
            "content": token,
        })

    # ── LLM 调用 ────────────────────────────────────────────────

    async def invoke_llm(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema: type[T],
        event_logger: EventLogger,
        workflow_id: uuid.UUID,
        task_name: str,
        *,
        request_meta: dict[str, Any] | None = None,
    ) -> T:
        """调用 LLM 获取结构化输出，全程流式推送 token 到前端。

        封装了三件事：
        1. 记录 LLM_REQUEST 事件（含 task_name 用于前端区分调用来源）
        2. 流式调用 LLM，每个 token 块广播到 SSE
        3. 从完整响应中提取 JSON 并校验为 Pydantic schema

        调用方仍需自行记录 LLM_RESPONSE，以便携带 schema 特有的摘要字段。
        """
        payload: dict[str, Any] = {"model_task": task_name}
        if request_meta:
            payload.update(request_meta)
        await self.log_and_broadcast(event_logger, EventType.LLM_REQUEST, payload, workflow_id)

        async def _on_token(token: str) -> None:
            await self.stream_llm_token(workflow_id, token)

        return await invoke_json_model(system_prompt, user_payload, schema, stream_callback=_on_token)
