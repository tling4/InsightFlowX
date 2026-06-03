"""多 Agent 编排运行时 —— 可复用的 StateGraph 执行引擎。

公共 API 一览：

    模板层（声明式定义）:
        GraphTemplate   完整的工作流图定义
        NodeSpec        单个节点的完整描述（agent + 策略 + 路由）
        AgentLike       Agent 协议（结构性子类型）
        RetryPolicy     重试配置（超时 / 次数 / 退避）

    数据载体:
        ArtifactDraft   制品草稿（由 ArtifactFactory 产出）
        NodeMetrics     单次执行指标
        NodeResult      Agent 返回值
        PauseRequest    暂停请求（人工审核触发）
        ControlDecision 路由决策结果

    执行层:
        GraphRuntime    编译 + 执行 StateGraph
        NodeFatalError  节点重试耗尽异常（含统一错误信息提取）
        execute_with_retry  带指数退避的节点执行器（GraphInterrupt 安全传播）

使用入口：
    from app.core.runtime import GraphRuntime, GraphTemplate, NodeSpec

    template = GraphTemplate(name="my_dag", entrypoint="node_a", nodes=(...))
    runtime = GraphRuntime(template, db, ...)
    final_state = await runtime.ainvoke(initial_data)
"""

from app.core.runtime.template import (
    ArtifactDraft,
    ControlDecision,
    GraphTemplate,
    NodeMetrics,
    NodeResult,
    NodeSpec,
    PauseRequest,
    RetryPolicy,
)
from app.core.runtime.graph_runtime import GraphRuntime
from app.core.runtime.retry import NodeFatalError, execute_with_retry

__all__ = [
    "ArtifactDraft",
    "ControlDecision",
    "execute_with_retry",
    "GraphRuntime",
    "GraphTemplate",
    "NodeFatalError",
    "NodeMetrics",
    "NodeResult",
    "NodeSpec",
    "PauseRequest",
    "RetryPolicy",
]
