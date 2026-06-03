"""图模板定义 —— 多 agent 编排的核心抽象层。

本模块定义了声明式工作流图所需的全部类型，与执行逻辑完全分离：

层次结构：
    GraphTemplate          完整的工作流图定义
      └── NodeSpec         图中每个节点（agent + 策略 + 路由配置）
            ├── AgentLike    agent 协议（async run 签名）
            ├── RetryPolicy  重试配置
            ├── PausePolicy  暂停策略（人工审核 Hook）
            ├── RoutePolicy  路由策略（决定下一步走向）
            └── ArtifactFactory  制品工厂（从输出中提取持久化数据）

控制流类型：
    ControlDecision  RoutePolicy 的决策结果（继续/跳转/暂停/完成/失败）
    PauseRequest     PausePolicy 的中断请求（携带前端选项列表）
    NodeResult       Agent 执行后的返回值（patch + 制品 + 指标）
    ArtifactDraft    待持久化的制品草稿
    NodeMetrics      单次 agent 调用指标
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Protocol

from app.core.runtime.context import AgentContext
from pydantic import BaseModel, Field


# ── 协议 ────────────────────────────────────────────────────────────────

class AgentLike(Protocol):
    """Agent 必须遵循的结构化协议。

    每个 agent 实现一个 async run 方法：
        - state: 当前工作流状态字典 {data, control, runtime, errors}
        - ctx:   运行时上下文（事件发射、LLM 调用等）
        - 返回:  patch dict，会被浅合并到 data 中

    协议允许结构性子类型 —— agent 不需要显式继承，
    只要签名为 async def run(self, state: dict, ctx: AgentContext) -> dict 即可。
    """

    async def run(self, state: dict, ctx: AgentContext) -> dict:
        ...


class PausePolicy(Protocol):
    """暂停策略协议 —— 决定节点执行后是否中断等待人工审核。

    在 gate node 中，先于 RoutePolicy 调用。
    如果返回 PauseRequest，则通过 langgraph.interrupt() 挂起图执行，
    等待人工通过 API 提交决策后继续。

    Args:
        state: 当前 RuntimeState 的子集 {data, control, runtime}
        spec:  当前节点的 NodeSpec
    Returns:
        PauseRequest | None  —— None 表示不需要暂停
    """

    def build_pause(self, state: dict, spec: "NodeSpec") -> PauseRequest | None:
        ...


class RoutePolicy(Protocol):
    """路由策略协议 —— 决定节点执行完成后图的下一步走向。

    在 gate node 中，PausePolicy（如果有）之后调用。
    返回的 ControlDecision 会被 gate node 翻译为：
        - continue: 走 default_next（默认前向边）
        - route:    跳转到指定的 next_node（触发条件边 + revision_count 递增）
        - finish:   正常结束，设置 terminal_status="completed"
        - fail:     异常结束，设置 terminal_status="failed"
        - pause:    保留字段，当前通过 PausePolicy + interrupt() 实现暂停

    Args:
        state: 当前 RuntimeState 的子集 {data, control, runtime}
        spec:  当前节点的 NodeSpec
    """

    def decide(self, state: dict, spec: "NodeSpec") -> ControlDecision:
        ...


# ── 配置模型 ────────────────────────────────────────────────────────────

class RetryPolicy(BaseModel):
    """节点重试配置。

    由 execute_with_retry 消费，控制单次 agent 调用的重试行为：
        max_attempts: 最大尝试次数（含首次，默认 3）
        timeout_sec:  单次调用超时秒数（默认 300）
        backoff_base_sec: 退避基数（第 n 次重试前等待 backoff_base^n 秒）
    """

    max_attempts: int = 3
    timeout_sec: int = 300
    backoff_base_sec: int = 2


# ── 数据载体 ────────────────────────────────────────────────────────────

class ArtifactDraft(BaseModel):
    """节点产出的制品草稿，由 ArtifactFactory 生成，NodeRunner 负责持久化到 Artifact 表。

    Attributes:
        artifact_type:   制品类型（collection_raw / feature_matrix / report 等）
        title:           前端展示标题
        content:         结构化内容（JSON）
        created_by_node: 产出节点 id
        content_text:    Markdown 等纯文本版本，用于前端预览
    """

    artifact_type: str
    title: str
    content: dict
    created_by_node: str
    content_text: str | None = None


class NodeMetrics(BaseModel):
    """单次 agent 调用的执行指标。

    由 agent 自行填充，NodeRunner 可选持久化到 WorkflowNodeState。
    """

    duration_ms: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    model_name: str = ""


class NodeResult(BaseModel):
    """Agent 执行后 NodeRunner 解析的标准返回值。

    patch 中的 key 会被浅合并到 data 中，以 "__" 开头的私有 key 会被剥离。
    """

    patch: dict = Field(default_factory=dict)
    artifacts: list[ArtifactDraft] = Field(default_factory=list)
    metrics: NodeMetrics = Field(default_factory=NodeMetrics)


class PauseRequest(BaseModel):
    """暂停请求 —— PausePolicy 的返回值，用于触发人工审核中断。

    options 列表定义了前端展示的操作按钮：
        [{"value": "jump", "label": "按建议重试", "target_node": "analysis"}, ...]

    to_interrupt_payload(state) 生成 langgraph.interrupt() 需要的标准载荷。
    """

    node_id: str
    reason: str = ""
    options: list[dict] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)
    suggested_route: str | None = None

    def to_interrupt_payload(self, state: dict) -> dict:
        """将 PauseRequest 序列化为 langgraph interrupt 标准载荷。

        Args:
            state: 当前 RuntimeState，用于提取 run_id / thread_id
        """
        runtime = state.get("runtime") or {}
        return {
            "paused_by_node": self.node_id,
            "pause_reason": self.reason,
            "pause_options": self.options,
            "pause_context": self.context,
            "suggested_route": self.suggested_route,
            "run_id": runtime.get("run_id"),
            "thread_id": runtime.get("thread_id"),
        }


class ControlDecision(BaseModel):
    """RoutePolicy 的决策结果，由 gate node 解释执行。

    action 取值：
        "continue"  直接进入 default_next
        "route"     跳转到 next_node（触发条件边，递增 revision_count）
        "pause"     保留字段，当前暂停由 PausePolicy + interrupt() 实现
        "finish"    正常终止，gate 设置 terminal_status="completed"
        "fail"      异常终止，gate 设置 terminal_status="failed" + terminal_reason
    """

    action: Literal["continue", "route", "pause", "finish", "fail"]
    next_node: str | None = None
    pause: PauseRequest | None = None
    reason: str = ""


# ── 回调类型 ────────────────────────────────────────────────────────────

ArtifactFactory = Callable[[dict, dict], list[ArtifactDraft]]
"""制品工厂签名。

Args:
    patch: agent 返回的 patch dict
    data:  合并 patch 后的完整 data dict
Returns:
    list[ArtifactDraft]  —— 要持久化的制品列表，空列表表示无制品
"""


# ── 图定义 ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class NodeSpec:
    """图中单个节点的完整描述。

    每个 NodeSpec 在编译时产生两个 langgraph 节点：
        {id}         业务节点（由 NodeRunner 调用 agent.run）
        {id}__gate   控制门（评估 PausePolicy → RoutePolicy → 条件路由）

    Attributes:
        id:              节点唯一标识（语义名，如 "analysis" / "review"）
        agent:           Agent 实现（遵循 AgentLike 协议）
        default_next:    默认下游节点 id，或 "done" 表示终止
        allowed_routes:  允许 route_policy 跳转到的一组节点 id
        retry_policy:    重试配置（超时 / 次数 / 退避）
        pause_policy:    暂停策略（None 表示该节点不暂停）
        route_policy:    路由策略（None 时使用 DefaultRoutePolicy）
        artifact_factory: 制品工厂（None 表示该节点不产出制品）
    """

    id: str
    agent: AgentLike
    default_next: str
    allowed_routes: tuple[str, ...] = ()
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    pause_policy: PausePolicy | None = None
    route_policy: RoutePolicy | None = None
    artifact_factory: ArtifactFactory | None = None

    @property
    def gate_id(self) -> str:
        """返回对应的控制门节点 id（格式：{node_id}__gate）。"""
        return f"{self.id}__gate"


@dataclass(frozen=True)
class GraphTemplate:
    """完整工作流图的声明式定义。

    包含节点列表和入口节点 id，与执行逻辑完全分离。
    GraphRuntime 接收此模板后编译为 langgraph StateGraph。

    Attributes:
        name:       图名称（用于日志和 runtime.template 标识）
        nodes:      节点列表（顺序不影响执行，路由由 RoutePolicy 决定）
        entrypoint: 入口节点 id（对应一个 NodeSpec.id）

    Usage:
        template = GraphTemplate(
            name="my_workflow",
            entrypoint="step_a",
            nodes=(NodeSpec(...), NodeSpec(...)),
        )
        runtime = GraphRuntime(template, ...)
        final_state = await runtime.ainvoke(initial_data)
    """

    name: str
    nodes: tuple[NodeSpec, ...]
    entrypoint: str

    def node(self, node_id: str) -> NodeSpec:
        """按 id 查找节点，KeyError 如果 id 不存在。"""
        for spec in self.nodes:
            if spec.id == node_id:
                return spec
        raise KeyError(f"Unknown node id: {node_id}")

    @property
    def node_ids(self) -> tuple[str, ...]:
        """所有节点 id 的元组（按声明顺序）。"""
        return tuple(spec.id for spec in self.nodes)
