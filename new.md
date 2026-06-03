# Reusable Multi-Agent StateGraph Runtime

本文档说明当前项目重构后的新架构，重点是后续如何维护、扩展和复用这套多 Agent 编排模板。

## 1. 核心目标

本项目现在不再把竞品分析流程写死为一组散落的 LangGraph 节点闭包，而是抽象为：

- `GraphTemplate`：一个可复用工作流模板。
- `NodeSpec`：一个业务节点声明。
- `AgentContext`：业务 agent 能看到的运行时上下文。
- `NodeRunner`：统一执行 agent、重试、落库、产物保存。
- `ControlGate`：每个业务节点后的控制节点，负责 pause、resume、route、finish。
- `GraphRuntime`：唯一负责把模板编译成 LangGraph 并执行的运行时。

核心原则：

- 业务 agent 只做业务输入输出。
- pause / route / retry / persistence 不写在 agent 里。
- LangGraph checkpoint 是恢复执行的真相。
- DB runtime 表保存运行实例、暂停请求、事件、快照、产物。

## 2. 当前目录职责

### Runtime 抽象层

```text
backend/app/core/runtime/
├── template.py       # GraphTemplate / NodeSpec / RetryPolicy / PauseRequest / ControlDecision
├── context.py        # AgentContext / EventSink
├── node_runner.py    # 执行业务 agent，处理 retry、snapshot、artifact
├── graph_runtime.py  # 编译并运行 StateGraph，插入 control gate
└── policies.py       # 可复用 pause / route policy
```

### 当前业务模板

```text
backend/app/core/competitive_template.py
```

`CompetitiveAnalysisTemplate` 是当前竞品分析业务对 runtime 的一个实例化：

```python
CompetitiveAnalysisTemplate = GraphTemplate(
    name="competitive_analysis",
    entrypoint="information_collection",
    nodes=(
        NodeSpec(...),
        NodeSpec(...),
        NodeSpec(...),
        NodeSpec(...),
    ),
)
```

### 工作流入口

```text
backend/app/core/workflow_executor.py
```

负责：

- 创建 / 获取 `WorkflowRun`
- 初始化 `GraphRuntime`
- start / resume / recover
- 将最终状态写回 `workflow` 和 `workflow_run`
- 持久化 `workflow_pause`
- 广播 workflow-level SSE

## 3. Runtime State 结构

统一使用 `RuntimeState`：

```python
class RuntimeState(TypedDict, total=False):
    data: dict
    control: dict
    runtime: dict
    errors: list[dict]
```

### `data`

业务数据，只由 agent 读写。

当前竞品分析里包括：

- `config`
- `raw_data`
- `feature_matrix`
- `pricing_comparison`
- `user_sentiment`
- `swot`
- `report`
- `review_result`

### `control`

运行控制数据，只由 runtime / gate / policy 读写。

典型字段：

- `current_node`
- `route_label`
- `revision_count`
- `max_revisions`
- `human_decision`
- `terminal_status`
- `terminal_reason`
- `last_decision`

### `runtime`

运行实例元信息，初始化后不应由 agent 修改。

典型字段：

- `workflow_id`
- `run_id`
- `execution_attempt`
- `thread_id`
- `template`

## 4. Agent 接口

所有 DAG agent 现在统一为：

```python
async def run(self, state: dict, ctx: AgentContext) -> dict:
    ...
```

例如：

```python
class AnalysisAgent(BaseAgent):
    node_name = "analysis"

    async def run(self, state: dict, ctx: AgentContext) -> dict:
        ...
        await self.emit_progress(
            ctx,
            stage="prepare_context",
            message="正在整理采集来源并建立比较上下文。",
        )
        return {
            "feature_matrix": ...,
            "pricing_comparison": ...,
        }
```

Agent 不应再接收：

- `EventLogger`
- `workflow_id`
- `db`
- `sse_manager`

这些都属于 runtime 基础设施。

## 5. AgentContext 与 EventSink

`AgentContext` 是 agent 唯一可见的运行时上下文：

```python
@dataclass(frozen=True)
class AgentContext:
    workflow_id: uuid.UUID
    run_id: uuid.UUID
    node_id: str
    iteration: int
    events: EventSink
    llm: Any = None
    tools: Any = None
```

`EventSink` 负责事件持久化和 SSE 广播：

```python
await ctx.events.emit(EventType.NODE_START, payload)
await ctx.events.progress(stage="...", message="...")
await ctx.events.stream_token(token)
```

`BaseAgent` 对这些方法做了封装：

```python
await self.log_and_broadcast(ctx, EventType.NODE_COMPLETE, payload)
await self.emit_progress(ctx, stage="...", message="...")
await self.invoke_llm(prompt, payload, Schema, ctx, "task_name")
```

## 6. NodeSpec

`NodeSpec` 是单个业务节点的声明：

```python
NodeSpec(
    id="review",
    agent=ReviewAgent(),
    default_next="done",
    allowed_routes=("information_collection", "analysis", "report_writing"),
    retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
    pause_policy=ReviewFailPausePolicy(),
    route_policy=ReviewRoutePolicy(),
)
```

字段含义：

- `id`：节点名，必须与图里的 route label 一致。
- `agent`：业务 agent。
- `default_next`：默认下一节点；终点写 `"done"`。
- `allowed_routes`：允许动态跳转的目标节点。
- `retry_policy`：节点级重试策略。
- `pause_policy`：是否需要人工中断。
- `route_policy`：节点执行后如何决定下一跳。
- `artifact_factory`：把 agent 输出转换为 artifact。

## 7. GraphTemplate

`GraphTemplate` 声明一个完整业务流程：

```python
GraphTemplate(
    name="competitive_analysis",
    entrypoint="information_collection",
    nodes=(...)
)
```

`GraphRuntime` 会将它编译为标准形态：

```text
business_node_A -> gate_A -> business_node_B -> gate_B -> ...
                         \-> dynamic route
                         \-> interrupt
                         \-> END
```

每个业务节点后都自动接一个 gate。

## 8. ControlGate 逻辑

ControlGate 在 `GraphRuntime._make_gate_node()` 中生成。

执行顺序：

1. 读取 `data/control/runtime`
2. 调用 `pause_policy.build_pause(...)`
3. 如需要暂停，调用 LangGraph `interrupt(payload)`
4. resume 后拿到 human decision，写入 `control["human_decision"]`
5. 调用 `route_policy.decide(...)`
6. 写入 `control["route_label"]`
7. LangGraph conditional edge 根据 `route_label` 跳转

这意味着：

- agent 不返回 `__pause__`
- agent 不写 `human_decision`
- agent 不写 `review_reroute_target`
- agent 不知道 LangGraph interrupt

## 9. Review 的特殊逻辑如何表达

Review 现在是普通业务节点，特殊性由 policy 表达。

### `ReviewFailPausePolicy`

当 `review_result.passed == False` 且未达到 `max_revisions` 时，生成：

```python
PauseRequest(
    node_id="review",
    reason="...",
    options=[
        {"value": "jump", ...},
        {"value": "approve", ...},
        {"value": "abort", ...},
    ],
    context={...},
    suggested_route="analysis",
)
```

### `ReviewRoutePolicy`

恢复后决定下一跳：

1. review 通过：finish
2. 达到最大修订次数：fail
3. 人工 jump target 有效：跳人工目标
4. 否则使用 `review_result.target_node`
5. 仍无效则 fallback 到 `analysis`

## 10. 持久化模型

### `workflow`

业务聚合根。

新增关键字段：

- `current_run_id`
- `execution_attempt`
- `pause_state`
- `langgraph_checkpoint_id`

### `workflow_run`

一次运行实例。

字段包括：

- `id`
- `workflow_id`
- `execution_attempt`
- `thread_id`
- `status`
- `entrypoint`
- `started_at`
- `completed_at`

每次 fresh retry 会创建新的 run。

### `workflow_pause`

当前或历史暂停请求。

字段包括：

- `workflow_id`
- `run_id`
- `node_name`
- `reason`
- `options`
- `context`
- `suggested_route`
- `is_resolved`
- `decision`

### 事件 / 快照 / 产物

以下表都新增了 `run_id`：

- `workflow_event`
- `workflow_node_state`
- `artifact`

这用于运行实例隔离。

## 11. API 变化

路径基本保持兼容。

### Workflow Detail

`GET /workflows/{id}` 新增：

```json
{
  "current_run_id": "..."
}
```

### 查询接口新增 run_id 参数

以下接口都支持：

```text
?run_id=<uuid>
```

包括：

```text
GET /workflows/{id}/events
GET /workflows/{id}/states
GET /workflows/{id}/artifacts
GET /workflows/{id}/trace
```

旧的 `execution_attempt` 参数仍保留。

推荐前端优先使用：

```text
run_id = workflow.current_run_id
```

而不是只依赖 `execution_attempt`。

## 12. 执行流程

### Start

```text
/start
  -> workflow.status = running
  -> run_workflow()
  -> create WorkflowRun
  -> GraphRuntime.ainvoke(initial_data)
  -> LangGraph checkpoint thread = workflow_id:run_id
```

### Pause

```text
ReviewAgent returns review_result
  -> ReviewFailPausePolicy builds PauseRequest
  -> ControlGate interrupt(payload)
  -> workflow.status = paused
  -> workflow.pause_state = UI metadata
  -> workflow_pause inserted
  -> workflow_run.status = paused
```

Pause payload 不包含完整 DAG state，也不复制 `raw_data` 大字段。

### Resume

```text
/decide action=jump
  -> resume_workflow()
  -> resolve current workflow_pause
  -> workflow.status = running
  -> GraphRuntime.aresume(decision)
  -> ControlGate reads decision
  -> ReviewRoutePolicy decides next node
```

### Approve / Abort

`approve` 和 `abort` 不再进入 graph，直接终结 workflow/run，并 resolve pause。

### Retry

当前 `/retry/{node}` 保留旧路径，但实际语义是 fresh run：

```text
workflow.execution_attempt += 1
workflow.current_run_id = None
workflow.status = running
run_workflow() creates new WorkflowRun
```

## 13. 如何新增一个节点

假设要新增 `risk_analysis` 节点：

1. 创建 agent：

```python
class RiskAnalysisAgent(BaseAgent):
    node_name = "risk_analysis"

    async def run(self, state: dict, ctx: AgentContext) -> dict:
        ...
        return {"risk_analysis": result}
```

2. 在 `competitive_template.py` 增加 `NodeSpec`：

```python
NodeSpec(
    id="risk_analysis",
    agent=RiskAnalysisAgent(),
    default_next="report_writing",
    allowed_routes=REROUTE_TARGETS,
    retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
)
```

3. 调整前一个节点的 `default_next`：

```python
analysis.default_next = "risk_analysis"
```

4. 如需人工暂停，新增 `PausePolicy`。

不需要改：

- `GraphRuntime`
- `NodeRunner`
- `workflow_executor`
- API

## 14. 如何新增一个工作流模板

如果后续要支持另一个业务，比如“投资研究多 Agent 流程”，可以创建：

```text
backend/app/core/investment_template.py
```

定义：

```python
InvestmentResearchTemplate = GraphTemplate(
    name="investment_research",
    entrypoint="macro_collection",
    nodes=(...)
)
```

然后在 executor 层根据 workflow 类型选择 template。

当前项目还没有 `workflow.template_name` 字段。如果要支持多模板，建议给 `workflow` 增加：

```text
template_name VARCHAR(64)
```

再在 executor 中：

```python
template = template_registry[workflow.template_name]
```

## 15. 迁移说明

空数据库启动时会自动建表。

已有数据库需要执行：

```text
backend/migrations/20260602_runtime_template.sql
```

因为 `Base.metadata.create_all()` 只会创建不存在的表，不会可靠补齐已有表的新列。

## 16. 当前注意事项

- 前端目前仍可用 `execution_attempt`，但推荐改为优先使用 `current_run_id`。
- `graph_nodes.py` 和 `orchestrator.py` 已不再承载旧执行逻辑，只保留 facade。
- `workflow_state.py` 已是 `RuntimeState` alias。
- `retry/{node}` 路径名保留兼容，但语义是 fresh run，不是真正从指定 node 恢复。
- 真正的 `from_node` retry 可在未来通过 `ControlDecision(route)` 和 checkpoint state 做扩展。

## 17. 关键测试

当前全量测试：

```powershell
conda run -n insightflow python -m pytest -q
```

结果：

```text
101 passed
```

新增/调整的重点测试：

- `tests/test_runtime_template.py`
- `tests/test_human_in_the_loop.py`
- `tests/test_node_progress.py`
- `tests/test_report_agent.py`

这些测试现在验证的是新 runtime 抽象，而不是旧的 `_execute_node` / `make_pause_router`。
