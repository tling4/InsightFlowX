"""人工审核暂停（Human-in-the-loop）的生命周期管理。

本模块处理 langgraph interrupt 从状态提取、持久化到解析的全流程。
与具体业务领域无关，可复用于任何 GraphTemplate。

四个函数覆盖完整的 pause 生命周期：

    图执行完毕 ──→ extract_interrupt_payload  从 final_state 中提取 __interrupt__ 数据
                      │
                      ▼
                  make_pause_state            构造 pause_state dict（包括 dag_state 快照）
                      │
                      ▼
                  persist_pause              写入 WorkflowPause 表（标记旧的为已解决）
                      │
              （前端展示暂停界面，用户提交决策）
                      │
                      ▼
                  resolve_pause              标记 WorkflowPause 为已解决，记录 decision

使用方：workflow_executor 中的 _handle_graph_result 和 _handle_graph_exception。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_pause import WorkflowPause
from app.db.models.workflow_run import WorkflowRun


def extract_interrupt_payload(final_state: dict | None) -> dict | None:
    """从 langgraph 执行后的最终状态中提取中断载荷。

    langgraph 通过 interrupt() 挂起时会在状态中注入 __interrupt__ key。
    这个 key 的值在不同 langgraph 版本中可能是：
        - 单个 dict
        - list[dict]（取第一个）
        - 有 .value 属性的对象（langgraph 内部包装类）
        - {"value": {...}} dict 包装

    此函数处理所有已知格式，返回标准化的 dict 或 None。

    Args:
        final_state: GraphRuntime.ainvoke/aresume 返回的 RuntimeState
    Returns:
        中断载荷 dict（包含 paused_by_node / pause_reason / pause_options 等）
        或 None（图正常完成，无中断）
    """
    if not isinstance(final_state, dict) or "__interrupt__" not in final_state:
        return None
    interrupt_value = final_state.get("__interrupt__")
    if isinstance(interrupt_value, (list, tuple)) and interrupt_value:
        interrupt_value = interrupt_value[0]
    if hasattr(interrupt_value, "value"):
        interrupt_value = interrupt_value.value
    elif isinstance(interrupt_value, dict) and "value" in interrupt_value:
        interrupt_value = interrupt_value["value"]
    return interrupt_value if isinstance(interrupt_value, dict) else {}


def make_pause_state(pause_data: dict) -> dict:
    """将中断载荷转换为 Workflow 模型上的 pause_state 字典。

    添加 paused_at 时间戳和 dag_state 快照字段。
    dag_state 保存暂停时的完整图状态，用于前端展示和恢复时的上下文参考。

    Args:
        pause_data: extract_interrupt_payload 的返回值
    Returns:
        workflow.pause_state 格式的字典
    """
    return {
        "paused_by_node": pause_data.get("paused_by_node", ""),
        "pause_reason": pause_data.get("pause_reason", ""),
        "pause_options": pause_data.get("pause_options", []),
        "pause_context": pause_data.get("pause_context", {}),
        "suggested_route": pause_data.get("suggested_route"),
        "run_id": pause_data.get("run_id"),
        "thread_id": pause_data.get("thread_id"),
        "dag_state": pause_data.get("dag_state", {}),
        "paused_at": datetime.now(timezone.utc).isoformat(),
    }


async def persist_pause(db: AsyncSession, workflow, run: WorkflowRun, pause_state: dict) -> None:
    """将暂停状态持久化到 WorkflowPause 表。

    在创建新的暂停记录前，先将同一 run 下所有未解决的暂停标记为 resolved。
    确保每个时刻只有一个活跃的暂停记录。

    Args:
        db:          数据库会话
        workflow:    Workflow ORM 对象
        run:         WorkflowRun ORM 对象
        pause_state: make_pause_state 的返回值
    """
    previous = await db.execute(
        select(WorkflowPause).where(
            WorkflowPause.workflow_id == workflow.id,
            WorkflowPause.run_id == run.id,
            WorkflowPause.is_resolved.is_(False),
        )
    )
    for pause in previous.scalars().all():
        pause.is_resolved = True
        pause.resolved_at = datetime.now(timezone.utc)

    db.add(WorkflowPause(
        id=uuid.uuid4(),
        workflow_id=workflow.id,
        run_id=run.id,
        node_name=pause_state.get("paused_by_node") or "",
        reason=pause_state.get("pause_reason") or "",
        options=pause_state.get("pause_options") or [],
        context=pause_state.get("pause_context") or {},
        suggested_route=pause_state.get("suggested_route"),
    ))


async def resolve_pause(db: AsyncSession, workflow, run: WorkflowRun, decision: dict) -> None:
    """标记暂停为已解决，记录用户决策。

    在 resume_workflow 中调用。将同一 run 下所有未解决的 WorkflowPause
    记录标记为 is_resolved=True，并写入 decision 内容。

    Args:
        db:       数据库会话
        workflow: Workflow ORM 对象
        run:      WorkflowRun ORM 对象
        decision: 用户决策字典（来自 DecisionRequest.model_dump()）
    """
    result = await db.execute(
        select(WorkflowPause).where(
            WorkflowPause.workflow_id == workflow.id,
            WorkflowPause.run_id == run.id,
            WorkflowPause.is_resolved.is_(False),
        )
    )
    for pause in result.scalars().all():
        pause.is_resolved = True
        pause.decision = decision
        pause.resolved_at = datetime.now(timezone.utc)
