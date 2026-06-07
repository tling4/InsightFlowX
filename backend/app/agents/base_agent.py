from typing import Any, TypeVar

from pydantic import BaseModel

from app.agents.agent_utils import invoke_json_model
from app.core.runtime.context import AgentContext
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

    async def log_and_broadcast(self, ctx: AgentContext, event_type: EventType, payload: dict) -> None:
        """Emit a semantic event through the runtime-owned event sink."""
        await ctx.events.emit(event_type, payload)

    async def emit_progress(
        self,
        ctx: AgentContext,
        *,
        stage: str,
        message: str,
        level: str = "info",
    ) -> None:
        """发送用户可见的节点过程说明，不暴露模型原始 token。"""
        await ctx.events.progress(stage=stage, message=message, level=level)

    async def stream_llm_token(self, ctx: AgentContext, token: str) -> None:
        """向 SSE 订阅者广播 LLM 流式输出的单个 token 块。

        与 log_and_broadcast 不同，这里不写数据库 — token 粒度太细，
        写入会产生大量 IO。前端通过 event_type="llm_stream" 区分。
        """
        await ctx.events.stream_token(token)

    # ── LLM 调用 ────────────────────────────────────────────────

    async def invoke_llm(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema: type[T],
        ctx: AgentContext,
        task_name: str,
        *,
        request_meta: dict[str, Any] | None = None,
        stream_response: bool = True,
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
        await self.log_and_broadcast(ctx, EventType.LLM_REQUEST, payload)

        async def _on_token(token: str) -> None:
            await self.stream_llm_token(ctx, token)

        return await invoke_json_model(
            system_prompt,
            user_payload,
            schema,
            stream_callback=_on_token if stream_response else None,
        )
