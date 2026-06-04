"""节点执行器 —— 单个 NodeSpec 的运行时执行逻辑。

NodeRunner 负责编译后图的业务节点中实际执行的每一步：
    1. 构建 AgentContext（注入 EventSink）
    2. 调用 execute_with_retry（包装 agent.run）
    3. 处理成功：合并 patch → 更新 control → 保存制品 → 保存状态快照
    4. 处理失败：保存错误快照 → 重新抛出 NodeFatalError

每个 GraphRuntime.compile() 实例化一个 NodeRunner，所有业务节点共享。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime.retry import NodeFatalError, execute_with_retry

try:
    from langsmith import traceable
except ImportError:
    def traceable(**kwargs):  # type: ignore[no-redef]
        return lambda fn: fn
from app.core.runtime.context import AgentContext, EventSink
from app.core.runtime.template import ArtifactDraft, NodeResult, NodeSpec
from app.db.models.artifact import Artifact
from app.db.queries.workflow_queries import get_workflow_by_uuid
from app.db.models.workflow_node_state import WorkflowNodeState
from app.services.event_service import EventLogger

_SKIP_SNAPSHOT_KEYS = {"messages", "raw_data"}


def sanitize_for_json(value) -> dict:
    """将 state dict 转换为 JSON 安全的快照。

    跳过超大 key（messages / raw_data），不可序列化的值转为字符串。
    用于存入 WorkflowNodeState.state_snapshot。
    """
    if not isinstance(value, dict):
        return {}
    sanitized = {}
    for key, item in value.items():
        if key in _SKIP_SNAPSHOT_KEYS:
            continue
        try:
            sanitized[key] = json.loads(json.dumps(item, default=str))
        except (TypeError, ValueError):
            sanitized[key] = str(item)
    return sanitized


class NodeRunner:
    """单个节点的运行时执行器。

    在 GraphRuntime.compile() 时创建，被所有业务节点闭包共享。
    负责：构造 AgentContext → 调用 agent.run（带重试）→ 组装 RuntimeState 返回值。

    Args:
        db:               数据库会话
        workflow_id:      工作流 UUID
        run_id:           本次执行实例 UUID
        execution_attempt:执行尝试号（用于制品和状态快照的隔离）
        event_logger:     事件日志器（会自动派生节点级 logger）
    """

    def __init__(
        self,
        db: AsyncSession,
        workflow_id: uuid.UUID,
        run_id: uuid.UUID,
        execution_attempt: int,
        event_logger: EventLogger,
    ):
        self.db = db
        self.workflow_id = workflow_id
        self.run_id = run_id
        self.execution_attempt = execution_attempt
        self.event_logger = event_logger

    @traceable(run_type="chain", name="node_execution")
    async def run(self, spec: NodeSpec, state: dict) -> dict:
        """执行单个 NodeSpec。

        完整执行流程：
            1. 拆解 RuntimeState → {data, control, runtime}
            2. 构造 AgentContext + EventSink
            3. execute_with_retry 调用 agent.run（含重试逻辑）
            4. 成功：合并 patch → 更新 control → 保存制品 + 状态快照
            5. 失败：保存错误快照 → 重新抛出 NodeFatalError
            6. 组装返回 RuntimeState（被 langgraph 用于下一个节点）

        Args:
            spec:  要执行的 NodeSpec
            state: 当前 RuntimeState dict

        Returns:
            更新后的 RuntimeState dict，data 中已合并 agent 返回的 patch
        """
        data = dict(state.get("data") or {})
        control = dict(state.get("control") or {})
        runtime = dict(state.get("runtime") or {})
        iteration = int(control.get("revision_count", data.get("revision_count", 0)) or 0)
        node_logger = self.event_logger.with_node(spec.id, iteration)
        ctx = AgentContext(
            workflow_id=self.workflow_id,
            run_id=self.run_id,
            node_id=spec.id,
            iteration=iteration,
            events=EventSink(node_logger, self.workflow_id, spec.id),
        )
        start = time.time()

        try:
            async def _agent_call(input_state: dict) -> dict:
                return await spec.agent.run(input_state, ctx)

            result = await execute_with_retry(
                _agent_call,
                data,
                spec.id,
                node_logger,
                retry_policy=spec.retry_policy,
            )
        except NodeFatalError as exc:
            duration_ms = int((time.time() - start) * 1000)
            await self._save_node_state(spec.id, iteration, data, control, duration_ms, True, exc.error_message)
            raise

        patch = {key: value for key, value in result.items() if not key.startswith("__")}
        node_result = NodeResult(patch=patch)
        new_data = {**data, **node_result.patch}
        if isinstance(node_result.patch.get("config"), dict):
            workflow = await get_workflow_by_uuid(self.db, self.workflow_id)
            if workflow:
                workflow.config = node_result.patch["config"]
        if "revision_count" in new_data:
            control["revision_count"] = new_data["revision_count"]
        if "max_revisions" in new_data:
            control["max_revisions"] = new_data["max_revisions"]
        control["current_node"] = spec.id
        control["last_node_completed_at"] = datetime.now(timezone.utc).isoformat()

        duration_ms = int((time.time() - start) * 1000)
        artifact_ids = await self._save_artifacts(spec, patch, new_data)
        snapshot = {
            "data": sanitize_for_json(new_data),
            "control": sanitize_for_json(control),
            "runtime": sanitize_for_json(runtime),
            "artifact_ids": [str(artifact_id) for artifact_id in artifact_ids],
        }
        await self._save_node_state(spec.id, iteration, snapshot, control, duration_ms)

        return {
            "data": new_data,
            "control": control,
            "runtime": runtime,
            "errors": list(state.get("errors") or []),
        }

    async def _save_node_state(
        self,
        node_name: str,
        iteration: int,
        state_snapshot: dict,
        control: dict,
        duration_ms: int = 0,
        is_error: bool = False,
        error_message: str | None = None,
    ) -> WorkflowNodeState:
        """持久化节点执行状态快照到 WorkflowNodeState 表。

        Args:
            node_name:      节点标识
            iteration:      修订次数
            state_snapshot: 经过 sanitize_for_json 处理后的状态快照
            control:        控制字段（用于未来扩展）
            duration_ms:    节点执行耗时（毫秒）
            is_error:       是否为错误快照
            error_message:  错误消息（仅在 is_error=True 时有值）
        """
        node_state = WorkflowNodeState(
            id=uuid.uuid4(),
            workflow_id=self.workflow_id,
            run_id=self.run_id,
            execution_attempt=self.execution_attempt,
            node_name=node_name,
            iteration=iteration,
            state_snapshot=sanitize_for_json(state_snapshot),
            artifact_ids=[],
            duration_ms=duration_ms,
            is_error=is_error,
            error_message=error_message,
        )
        self.db.add(node_state)
        await self.db.commit()
        return node_state

    async def _save_artifacts(self, spec: NodeSpec, patch: dict, data: dict) -> list[uuid.UUID]:
        """调用 NodeSpec.artifact_factory 生成并持久化制品列表。

        Args:
            spec:  当前 NodeSpec
            patch: agent 返回的 patch
            data:  合并 patch 后的完整 data
        Returns:
            已持久化制品的 UUID 列表
        """
        if spec.artifact_factory is None:
            return []
        artifact_ids: list[uuid.UUID] = []
        for draft in spec.artifact_factory(patch, data):
            artifact_ids.append(await self._save_artifact(draft))
        return artifact_ids

    async def _save_artifact(self, draft: ArtifactDraft) -> uuid.UUID:
        """将单个 ArtifactDraft 持久化到 Artifact 表。

        Args:
            draft: 由 ArtifactFactory 产出的制品草稿
        Returns:
            已持久化制品的 UUID
        """
        artifact = Artifact(
            id=uuid.uuid4(),
            workflow_id=self.workflow_id,
            run_id=self.run_id,
            execution_attempt=self.execution_attempt,
            artifact_type=draft.artifact_type,
            title=draft.title,
            content=draft.content,
            content_text=draft.content_text,
            created_by_node=draft.created_by_node,
        )
        self.db.add(artifact)
        await self.db.commit()
        return artifact.id
