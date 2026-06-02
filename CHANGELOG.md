# Changelog

## 2026-06-02

### 15. 结构化输出、重试语义与僵尸工作流修复

这次主要把三条容易互相污染的链路收拢成了按 `execution_attempt` 隔离的执行模型：agent 输出不再只依赖 prompt，retry 不再复用旧 checkpoint，前端打开工作流页时也会先校验当前 attempt 的状态，再决定是否恢复。

#### 修复方案

- **结构化输出兜底**：`invoke_json_model` 增加“先解析校验，失败后自动修复再试一次”的兜底层。先把 LLM 原始响应抽取成 JSON，再用 Pydantic 校验；若失败，会把 `expected_schema` / `invalid_output` / `validation_error` 重新喂给模型生成修复版结果，避免把结构化能力完全押在 prompt 或 LangChain output parser 上。
- **重试与 checkpoint 隔离**：retry 入口改为创建新的 `execution_attempt`，并将 LangGraph `thread_id` 改为 `workflow_id:execution_attempt`。这样新一轮执行不会读到旧 checkpoint；同时 retry / recover / resume 的后台任务改为使用请求绑定的 engine，避免测试或异步场景下出现跨 loop 的 session 问题。没有初始化 checkpointer 时，后台任务会优雅跳过而不是直接抛错。
- **僵尸工作流恢复**：前端工作流页在进入运行/暂停/报告页时，会按当前 attempt 拉取 events、states、artifacts 和 trace，并在页面打开时判断是否需要从最近 checkpoint 恢复。报告页与 trace/artifact 查询也都改为按 attempt 过滤，避免混入上一轮执行数据。

#### 变更文件

- `backend/app/agents/agent_utils.py`
- `backend/app/services/workflow_service.py`
- `backend/app/core/workflow_executor.py`
- `backend/app/api/v1/workflow.py`
- `backend/app/api/v1/event.py`
- `backend/app/api/v1/artifact.py`
- `backend/app/api/v1/trace.py`
- `frontend/app/workflows/[id]/page.tsx`
- `frontend/lib/use-artifacts.ts`
- `frontend/lib/use-trace.ts`
- `frontend/types/workflow.ts`

#### 验证

- `backend/tests/test_human_in_the_loop.py -k "retry or recover or pause_router"` 通过
- 前端 `eslint` 已跑，仓库里仍有若干与本次无关的既有 lint 问题

### 16. 修复 review reroute 条件路由的 dict 哈希错误
这次修复了 `review` 节点在 LangGraph conditional edges 中返回 `Command` 导致的 `unhashable type: 'dict'` 崩溃。现在 router 只返回可 hash 的节点名字符串，review 恢复路径会把一次性的 reroute 目标写入独立字段，并清理旧的 `human_decision` / `cached_review_result`，避免旧跳转在后续节点里反复生效。

#### 修复方案

- **条件路由收敛为字符串**：`make_pause_router()` 不再返回 `Command`，而是统一返回 `information_collection` / `analysis` / `report_writing` / `done` 这类可 hash 的路由标签，避免 LangGraph 在分支收尾阶段对 `dict` 参与哈希查找。
- **review 恢复路径一次性消费**：`review` 节点恢复缓存结果时，新增 `review_reroute_target` 和 `review_result_consumed` 两个状态字段。router 先消费显式 reroute 目标，再在未消费时读取 `review_result.target_node`，保证人工 jump 和 agent 建议都只生效一次。
- **测试契约同步**：更新 HITL 测试，覆盖 review 恢复时清理旧决策、保留 reroute 目标，以及条件路由直接返回字符串的行为。

#### 变更文件

- `backend/app/core/orchestrator.py`
- `backend/app/core/graph_nodes.py`
- `backend/app/agents/review_agent.py`
- `backend/app/schemas/workflow_state.py`
- `backend/tests/test_human_in_the_loop.py`

#### 验证

- `C:\Users\Void\.conda\envs\insightflow\python.exe -m pytest backend\tests\test_human_in_the_loop.py -q` 通过
- `C:\Users\Void\.conda\envs\insightflow\python.exe -m pytest backend\tests\test_workflow_executor.py -q` 通过
- `C:\Users\Void\.conda\envs\insightflow\python.exe -m py_compile backend\app\core\orchestrator.py backend\app\core\graph_nodes.py backend\app\agents\review_agent.py backend\app\schemas\workflow_state.py backend\tests\test_human_in_the_loop.py` 通过

### 17. 修复 report_agent 在部分缺源时过早退回兜底模板
之前 `report_writing` 节点只要命中 `collection_errors["__source_coverage__"]`，就会直接走“资料不足”报告，导致即使已有足够的可用来源，也看起来像跳过了 LLM 生成。现在这类“缺一个竞品来源”的情况只作为提示输入给 LLM，不再硬停；只有竞品解析失败或完全没有可用来源时才退回兜底报告。

#### 修复方案

- **放宽硬门槛**：`__source_coverage__` 从硬失败改为提示项，部分缺源时仍允许 `invoke_llm()` 生成正式报告。
- **保留真正的硬失败**：竞品解析失败，或全部来源为 0 时，仍然回退到“资料不足”报告，避免完全空数据时编造内容。
- **测试覆盖**：新增 `test_report_agent.py`，覆盖“部分缺源仍走 LLM”和“竞品解析失败仍回退”两种路径。

#### 变更文件

- `backend/app/agents/report_agent.py`
- `backend/tests/test_report_agent.py`

#### 验证

- `C:\Users\Void\.conda\envs\insightflow\python.exe -m pytest backend\tests\test_report_agent.py -q` 通过
- `C:\Users\Void\.conda\envs\insightflow\python.exe -m pytest backend\tests\test_workflow_executor.py -q` 通过
- `C:\Users\Void\.conda\envs\insightflow\python.exe -m py_compile backend\app\agents\report_agent.py backend\tests\test_report_agent.py` 通过

### 18. 将 DAG 右侧栏从 LLM token 流改为节点过程叙述
之前前端工作流运行页右侧边栏直接消费 `llm_stream`，用户会看到模型逐 token 推送的原始输出，既不稳定，也暴露了不适合面向用户的底层信息。现在右侧栏改为展示节点级的“过程叙述”：后端主动发送可读的阶段说明，前端按节点聚合、回放和切换查看；原始事件只在显式调试开关下保留。

#### 修复方案

- **新增用户态过程事件**：在后端事件契约中新增 `node_progress`，并在 `BaseAgent` 中增加 `emit_progress()` helper。事件 payload 统一为 `stage` / `message` / `level`，用于表达“正在解析竞品”“正在整理定价信息”“正在给出审查结论”这类用户可读过程，而不是暴露模型原始推理或 token。
- **四个业务 Agent 补发过程文案**：`CollectionAgent`、`AnalysisAgent`、`ReportAgent`、`ReviewAgent` 都在关键阶段发出稳定的过程说明；其中 `review` 失败时会明确给出建议回退节点，进入人工决策暂停时，过程文案与 `pause_reason` 保持一致。
- **前端右栏重构为过程面板**：运行态右侧栏不再消费 `llm_stream`，而是按节点维护过程条目数组，展示 `node_progress`、节点生命周期、`review_fail`、`reroute`、`workflow_paused/failed/complete` 等事件。页面刷新后会通过 `/events` 回放重建过程面板；调试模式下可用 `NEXT_PUBLIC_ENABLE_DEBUG_EVENTS=true` 额外显示原始事件面板。
- **收拢前后端事件语义**：前端移除对不存在的 `review_reroute` 依赖，统一只认后端真实发送的 `reroute`，避免运行态展示层继续漂移。

#### 变更文件

- `backend/app/schemas/event.py`
- `backend/app/agents/base_agent.py`
- `backend/app/agents/collection_agent.py`
- `backend/app/agents/analysis_agent.py`
- `backend/app/agents/report_agent.py`
- `backend/app/agents/review_agent.py`
- `backend/tests/test_node_progress.py`
- `frontend/types/event.ts`
- `frontend/lib/use-node-stream.ts`
- `frontend/components/events/stream-panel.tsx`
- `frontend/components/events/event-console.tsx`
- `frontend/app/workflows/[id]/page.tsx`

#### 验证

- `conda run -n insightflow pytest backend\tests -q` 通过（`101 passed`）
- `cmd /c npm run lint` 未通过，原因是当前环境缺少可执行的 `eslint`，不是本次改动触发的代码错误

## 2026-05-25

### 1. 增加全局异常处理架构

引入 Java Spring `@ExceptionHandler` 风格的全局异常处理机制，替换原有的 `return None` + 手动 `HTTPException` 模式。

#### 修复方案

定义 `AppException` 基类（携带 `error_code` / `message` / `status_code` / `details`）及 7 个子类。在 `main.py` 注册全局异常 handler：`AppException` → 结构化 JSON 响应；`Exception` → 500 兜底。所有 service / dependency / API 路由中的 `return None` 和 `raise HTTPException` 替换为对应的业务异常。

#### 新增文件

- `backend/app/exceptions.py` — 业务异常层级：`AppException` 基类 + 7 个子类（`WorkflowNotFoundError`、`InvalidStateTransitionError`、`ConfigIncompleteError`、`InvalidCredentialsError`、`InvalidTokenError`、`DuplicateResourceError`、`ArtifactNotFoundError`）

#### 修改的文件

- `backend/app/main.py` — 注册全局 handler
- `backend/app/services/workflow_service.py` — `return None` → `raise` 对应异常
- `backend/app/services/auth_service.py` — `authenticate_user` 返回 None → `raise InvalidCredentialsError`
- `backend/app/dependencies.py` — 4 处 `raise HTTPException(401)` → `raise InvalidTokenError`
- `backend/app/api/v1/*.py` — 移除 `HTTPException` 导入，手动 `raise HTTPException` → 业务异常

---

### 2. 结构化错误记录与节点状态修复

#### 修复方案

新增 `_extract_error_info()` 解包 `NodeFatalError.last_error` 获取 `AppException` 的结构化字段。抽取 `_execute_node()` 公共 helper，统一在 `NodeFatalError` 时保存 `WorkflowNodeState` 并标记 `is_error=True`，修复 `is_error` 列从未被使用的死字段。

#### 修改的文件

- `backend/app/core/workflow_executor.py` — 新增 `_extract_error_info()`，`WORKFLOW_FAILED` payload 包含结构化错误信息
- `backend/app/core/node_executor.py` — `NODE_ERROR` payload 使用业务 `error_code`
- `backend/app/core/graph_nodes.py` — 抽取 `_execute_node()`，统一错误快照保存

---

### 3. 查询层重构

将分散在各 service 和 API 路由中的 15 处 SQLAlchemy 内联查询抽取到 `backend/app/db/queries/` 目录，按业务域分文件。

#### 新增文件

- `backend/app/db/queries/user_queries.py` — `get_user_by_email`、`get_user_by_username`、`get_user_by_id`
- `backend/app/db/queries/workflow_queries.py` — `get_workflow_by_id`、`get_workflow_by_uuid`、`get_user_workflows`、`get_message_history`
- `backend/app/db/queries/event_queries.py` — `get_events`、`count_events`、`get_node_states`
- `backend/app/db/queries/artifact_queries.py` — `get_workflow_artifacts`、`get_artifact_by_id`、`get_artifact_ids_by_workflow`、`get_trace_links`

---

### 4. 安全与代码质量修复

修复 5 个安全及代码质量问题。

#### 修复方案

- **模块级副作用改为懒初始化**：`tavily_client` 和 `interview_agent` 从模块导入时实例化改为首次调用时懒初始化，避免 API key 为空或 LLM 配置错误时静默失败
- **JWT 密钥强制显式配置**：`JWT_SECRET_KEY` 移除不安全默认值 `"change-me-in-production"`，未配置时启动即报错
- **创建 Workflow 改用 JSON body**：`POST /workflows` 的 `title` 参数从 query string 改为 JSON 请求体 `WorkflowCreate` schema
- **密码与用户名添加长度校验**：`UserRegister.password` 要求 `min_length=8`，`username` 要求 `min_length=3`
- **认证接口添加频率限制**：新增 `RateLimiter` 内存固定窗口实现，登录 10 次/60s，注册 5 次/60s，超限返回 429

#### 新增文件

- `backend/app/services/rate_limiter.py` — 内存固定窗口频率限制器

#### 修改的文件

- `backend/app/services/interview_service.py` — 懒初始化 `tavily_client` / `interview_agent`；`import json` 移至顶部
- `backend/app/config.py` — `JWT_SECRET_KEY` 移除默认值，强制配置
- `backend/app/schemas/workflow.py` — 新增 `WorkflowCreate` 请求体 schema
- `backend/app/api/v1/workflow.py` — `create_new_workflow` 从 query param 改为 Body
- `backend/app/schemas/auth.py` — `password` / `username` 添加 `min_length` 校验
- `backend/app/api/v1/auth.py` — `login` / `register` 添加 `Depends(rate_limit)`
- `backend/tests/conftest.py` — 添加 `JWT_SECRET_KEY` 测试默认值；覆盖 rate limiter 为 no-op
- `backend/tests/test_api/*.py` — 更新密码长度和 JSON body 调用方式
- `backend/tests/test_exceptions.py` — 同步更新

---

### 5. 引入 execution_attempt 执行批次隔离机制

节点级操作（event 写入、node_state 快照、artifact 产出）各自独立 `db.commit()`，导致外层 `db.rollback()` 是死代码——失败时所有已持久化的数据无法回滚。同时 retry 端点重跑 DAG 时，新旧两次执行的 events/node_states/artifacts 混在同一 `workflow_id` 下，无法按执行批次区分。

#### 修复方案

在 `Workflow`、`WorkflowEvent`、`WorkflowNodeState`、`Artifact` 四张表各新增 `execution_attempt` 整数列（DEFAULT 1）。每次 `run_workflow` 调用从 `workflow.execution_attempt` 读取当前批次号，全链路透传至所有写入点。retry 端点将 `workflow.execution_attempt += 1`，后续执行的所有行自动带上新批次号。移除 `workflow_executor.py` 中的死代码 `db.rollback()`，替换为注释说明节点级 commit 的设计意图。查询函数增加可选 `execution_attempt` 过滤参数。

#### 新增文件

- `backend/migrations/001_add_execution_attempt.sql` — 4 张表加列的数据库迁移脚本

#### 修改的文件

- `backend/app/db/models/workflow.py` — `Workflow` 新增 `execution_attempt` 列
- `backend/app/db/models/workflow_event.py` — `WorkflowEvent` 新增 `execution_attempt` 列
- `backend/app/db/models/workflow_node_state.py` — `WorkflowNodeState` 新增 `execution_attempt` 列
- `backend/app/db/models/artifact.py` — `Artifact` 新增 `execution_attempt` 列
- `backend/app/services/event_service.py` — `EventLogger` 构造函数接收并透传 `execution_attempt`；`log()` 写入；`with_node()` 传播
- `backend/app/core/graph_nodes.py` — `_save_node_state`、`_save_artifact`、`_execute_node`、4 个工厂函数全链路透传 `execution_attempt`
- `backend/app/core/orchestrator.py` — `compile_workflow_graph` 接收 `execution_attempt` 并传入 4 个工厂
- `backend/app/core/workflow_executor.py` — 从 `workflow.execution_attempt` 读取并传入下游；删除无意义的 `db.rollback()`，替换为注释说明
- `backend/app/api/v1/workflow.py` — retry 端点 `workflow.execution_attempt += 1`，返回值附带新批次号
- `backend/app/db/queries/event_queries.py` — `get_events`、`count_events`、`get_node_states` 新增可选 `execution_attempt` 过滤参数
- `backend/app/db/queries/artifact_queries.py` — `get_workflow_artifacts`、`get_artifact_ids_by_workflow` 新增可选 `execution_attempt` 过滤参数

#### 可能的潜在问题

- **部分 attempt 数据不完整**：DAG 跑到中途崩溃时，已执行节点的事件/产物已持久化（该 attempt 内部不完整），但查询时可通过 `execution_attempt` 过滤。不影响后续 attempt
- **老 attempt 数据堆积**：无自动清理机制，失败的 attempt 数据永久保留。后续可按需增加 TTL 清理或手动归档

---

## 2026-05-26

### 6. Agent 层 LLM 流式输出与调用模式工程化

原有 `invoke_json_model` 在三个分析 agent（analysis / report / review）中使用 `ainvoke` 一次性获取完整响应，SSE 层只能广播粗粒度的生命周期事件（NODE_START / NODE_COMPLETE / LLM_RESPONSE），前端看不到 LLM 逐 token 生成的实时进度。同时三个 agent 各自重复相同的调用样板代码（LLM_REQUEST 日志 → on_token 闭包 → invoke_json_model）。

#### 修复方案

**流式输出**：`invoke_json_model` 新增可选 `stream_callback` 参数。当传入回调时走 `astream` 逐 chunk 推送 token，否则回退到 `ainvoke`；两种路径最终都经过 `extract_json_object` → Pydantic 校验链。`BaseAgent` 新增 `stream_llm_token` 方法，将 token 以 `LLM_STREAM` 事件类型通过 SSE 广播（不写 DB，避免 token 粒度写入撑爆数据库）。`EventType` 枚举新增 `LLM_STREAM = "llm_stream"`。

**模式提取**：在 `BaseAgent` 中新增泛型方法 `invoke_llm(system_prompt, user_payload, schema, event_logger, workflow_id, model_task, ...)`，封装完整调用链：记录 LLM_REQUEST → 创建内部 `_on_token` 回调（调用 `stream_llm_token`）→ 传入 `invoke_json_model` → 返回 Pydantic 结构化对象。三个 agent 不再直接导入 `invoke_json_model`。

**可读性**：7 个 agent 文件全面补充注释，说明每处非显而易见的 WHY：JSON 提取两阶段策略、AnalysisBundle 单次调用设计、引用构建与 LLM 分离的原因、哨兵 vs 宽松 JSON 匹配的可靠性差异、asyncio.gather 的异常隔离策略、搜索模板按产品类别的差异化设计等。

#### 新增文件

（无）

#### 修改的文件

- `backend/app/schemas/event.py` — `EventType` 新增 `LLM_STREAM = "llm_stream"`
- `backend/app/agents/agent_utils.py` — `invoke_json_model` 新增可选 `stream_callback` 参数；新增 `StreamCallback` 类型别名；补充核心函数文档注释
- `backend/app/agents/base_agent.py` — 新增 `stream_llm_token`（SSE 广播 token，不写 DB）和 `invoke_llm`（泛型 LLM 调用封装）两个方法；补充三段式方法分组注释
- `backend/app/agents/analysis_agent.py` — 移除 `invoke_json_model` 直接导入；LLM 调用改为 `self.invoke_llm(...)`；补充注释
- `backend/app/agents/report_agent.py` — 同上；补充引用构建与 LLM 分离的设计注释
- `backend/app/agents/review_agent.py` — 同上；补充规则审查四维度及硬性门槛注释
- `backend/app/agents/collection_agent.py` — 补充搜索模板设计、并发隔离策略、URL 去重注释
- `backend/app/agents/interview_agent.py` — 补充架构差异说明（独立于 DAG、哨兵机制）、清理未使用的 `HumanMessage` 导入

#### 可能的潜在问题

- **JSON 提取仍依赖 prompt engineering**：当前 LLM 通过系统提示中的手写 JSON schema 文本输出自由格式 JSON，再由 regex 提取、Pydantic 校验。schema 变更需同时修改系统提示和 Pydantic model，容易不同步。代码中已标注迁移路径：后续替换为 `with_structured_output()` / function calling，届时 `extract_json_object` 和系统提示中的手写 schema 即可删除

---

### 7. 人在回路 (Human-in-the-Loop) 机制

引入泛化的人在回路暂停/恢复机制，使任意 agent 可在需要人工决策时暂停 DAG 执行，并通过 SSE 推送决策选项到前端，待用户决策后从断点恢复。

#### 核心设计

- **暂停信号**：agent 通过返回值约定 `{"__pause__": True, "pause_reason": "...", "pause_options": [...], ...}` 表达需要人工输入，不抛业务异常
- **LangGraph 原生中断**：`_execute_node` 检测到 `__pause__` 后调用 LangGraph `interrupt()` 暂停图执行，checkpoint 自动保存
- **恢复机制**：`POST /{id}/decide` 端点接收人工决策（resume/jump/approve/abort），通过 `Command(resume=..., update=...)` 从 checkpoint 恢复，`human_decision` 注入 state 避免无限循环
- **PostgreSQL checkpointer**：引入 `langgraph-checkpoint-postgres`，替代手动 JSON 序列化 state，支持进程重启后恢复
- **`run_workflow` 三态处理**：completed / paused / failed，暂停时 `finally` 跳过 `close_workflow()` 保持 SSE 连接
- **review agent 适配**：不再自动递增 `revision_count` 并重试，而是返回 `__pause__` 暂停信号

#### 新建文件

- `backend/app/schemas/decision.py` — `DecisionAction` 枚举（resume/jump/approve/abort）、`DecisionRequest` schema
- `backend/app/core/checkpointer.py` — PostgreSQL `PostgresSaver` 单例管理，懒初始化 + `setup()`

#### 修改的文件

- `backend/app/schemas/event.py` — `EventType` 新增 `WORKFLOW_RESUMED`；已有 `WORKFLOW_PAUSED` 开始使用
- `backend/app/schemas/workflow.py` — `WorkflowStatus` 新增 `PAUSED`
- `backend/app/schemas/workflow_state.py` — `WorkflowState` 新增 `human_decision: dict` 可选字段
- `backend/app/db/models/workflow.py` — `Workflow` 新增 `pause_state` JSON 列（存暂停元数据，checkpoint 负责 DAG state）
- `backend/app/core/node_executor.py` — `execute_with_retry` 新增 `except GraphInterrupt: raise`，暂停信号不被重试
- `backend/app/core/graph_nodes.py` — `_execute_node` 检测 `__pause__` 并调用 `interrupt()`；恢复路径合并 `human_decision` 并递增 `revision_count`
- `backend/app/core/orchestrator.py` — `compile_workflow_graph` 新增 `checkpointer` 参数；`_review_router` 优先使用 `human_decision` 中的 `target_node`
- `backend/app/core/workflow_executor.py` — `run_workflow` 新增 `except GraphInterrupt` 三态处理；新增 `resume_workflow` 函数；`finally` 中 `status != "paused"` 才关闭 SSE
- `backend/app/agents/review_agent.py` — `passed=False` 时返回 `__pause__` 信号，包含 pause_options 和 pause_context；达重试上限时正常返回
- `backend/app/api/v1/workflow.py` — 新增 `POST /{id}/decide`（resume 走后台恢复，approve/abort 同步完成）；修改 `POST /{id}/retry/{node_name}` 支持 `paused` 状态；详情接口新增 `pause_state` 字段
- `backend/app/main.py` — `lifespan` 启动事件中预热 checkpointer
- `backend/pyproject.toml` — 新增 `langgraph-checkpoint-postgres` 依赖

#### 可能的潜在问题

- **interrupt() 后节点重新执行**：LangGraph 从 checkpoint 恢复时会重新执行整个节点函数。通过 `human_decision` 注入 state 并检查 `state.get("human_decision")` 来跳过二次暂停，但 agent 的 LLM 调用也会重新执行，带来额外的 token 开销。后续可考虑通过 `_execute_node` 的快速路径优化，在有 `human_decision` 时跳过 agent 调用直接返回缓存结果。
- **checkpointer 表与业务表不在同一事务**：`checkpoints`/`checkpoint_blobs`/`checkpoint_writes` 三张表由 LangGraph checkpointer 独立管理（通过 psycopg 连接池），与 SQLAlchemy 管理的业务表不在同一事务边界。极端情况下可能出现业务表标记为 paused 但 checkpoint 未保存（或反之），导致 resume 时状态不一致。当前通过先保存 checkpoint（interrupt 内部），再提交业务事务来降低风险，但无法完全消除。
- **并发恢复风险**：当前未对 `workflow.status` 加乐观锁或分布式锁，理论上可能有两个并发 `POST /decide` 同时触发 resume。后续可增加 `status` 字段的 CAS 检查或引入 Redis 分布式锁。

---

## 2026-05-27

### 8. 通用化人在回路 Jump 机制与 Resume 优化

原有 pause→resume 机制存在三个问题：(1) `resume` 和 `jump` 语义完全重叠，`resume` 没有独立价值；(2) `_review_router` 混杂了 review 特有判断（passed、max_revisions），无法用于其他节点的暂停后跳转；(3) resume 时 ReviewAgent 用相同 state 重新跑一遍 LLM，浪费 token 调用。

#### 修复方案

- **删除 `resume`，统一为 `jump`**：`DecisionAction` 枚举移除 `RESUME`，只保留 `JUMP`/`APPROVE`/`ABORT`。人工 `target_node` 始终优先于 agent 建议
- **Router 通用化**：`_review_router` → 工厂函数 `make_pause_router(default_next)`，不再检查 `passed` 或 `revision_count >= max_revisions`。这些控制权归还给 agent 自身——通过是否设置 `target_node` 来决定是否触发 reroute。新路由逻辑：人工 jump + 有效 target_node → agent 建议 target_node → `default_next`（正常流程）。所有四个 DAG 节点均使用条件边（`add_conditional_edges`），任意节点返回 `__pause__` 后均可跳转到 reroute 目标，不再只有 review 节点支持
- **Resume 跳过重复 LLM 调用**：`resume_workflow` 从 `workflow.pause_state.dag_state` 中提取缓存的 `review_result`，通过 `Command(update={"cached_review_result": ...})` 注入 state。`make_review_node` 检测到 `human_decision` + `cached_review_result` 同时存在时，直接返回缓存结果并递增 `revision_count`，完全跳过 `ReviewAgent.run()` 和 `_execute_node`
- **事件补全**：`REVIEW_REROUTE` → 通用 `REROUTE`（任何节点暂停后的跳转）；新增 `REVIEW_FAILED_MAX_REVISIONS`（修订次数达上限）；`approve` 路径补发 `WORKFLOW_COMPLETE` + SSE；`abort` 路径补发 `WORKFLOW_FAILED`（error_code=USER_ABORTED）+ SSE
- **pause_options 更新**：`retry` → `jump`，与 API action 名称一致

#### 修改的文件

- `backend/app/schemas/decision.py` — 删除 `DecisionAction.RESUME`；更新 `target_node` 字段描述
- `backend/app/schemas/event.py` — `REVIEW_REROUTE` → `REROUTE`；新增 `REVIEW_FAILED_MAX_REVISIONS`
- `backend/app/schemas/workflow_state.py` — 新增 `cached_review_result: Optional[dict]` 字段
- `backend/app/core/orchestrator.py` — `_review_router` → `make_pause_router(default_next)` 工厂函数；抽取 `REROUTE_TARGETS` 常量；三处 `add_edge` 硬边替换为 `add_conditional_edges`，所有节点均可暂停后跳转
- `backend/app/agents/review_agent.py` — max_revisions 时发出 `REVIEW_FAILED_MAX_REVISIONS` 事件；`pause_options` 中 `retry` → `jump`
- `backend/app/core/graph_nodes.py` — `make_review_node`：检测 `cached_review_result` 时跳过 agent 重跑，直接返回缓存结果
- `backend/app/core/workflow_executor.py` — `resume_workflow`：提取缓存 `review_result` 注入 `Command.update`；发出通用 `REROUTE` 事件；删除 `resume` 动作判断
- `backend/app/api/v1/workflow.py` — `approve`/`abort` 补全 `EventLogger` + SSE 广播；删除 `resume` 分支；`jump` 改为唯一的 DAG 恢复动作
- `backend/tests/test_human_in_the_loop.py` — 类名 `TestReviewRouter` → `TestPauseRouter`；`_pause_router` → `make_pause_router("done")`；新增 5 个测试（cached_review_result 跳过、max_revisions 事件、approve/abort SSE）；delete 基于 `RESUME` 的测试用例

#### 可能的潜在问题

- **缓存仅覆盖 review 节点**：当前 `cached_review_result` 机制专门针对 review 节点的 LLM 跳过。若未来其他节点（如 analysis、report）也加入 `__pause__` 并在 resume 时需要跳过重复 LLM 调用，需要为该节点添加类似的缓存 key 和跳过逻辑
- **Router 依赖 agent 配合**：`_pause_router` 的 fallback 分支（agent 建议 target_node）当前只检查 `state["review_result"]`。若未来其他 agent 也需要建议 target_node，需在 router 中增加对应的 state key 检查，或建立统一的 state 字段约定

---

## 2026-05-28

### 9. 前端 Markdown 渲染与 DAG 画布稳定性修复

#### 修复方案

- **Markdown 渲染**：安装 `@tailwindcss/typography` 插件并在 `globals.css` 注册 `@plugin` 指令。Tailwind v4 默认不含 typography 插件，导致 chat-stream 和 report-viewer 中所有 `prose-*` 类均为空操作。插件激活后已写的 prose 类自动生效，同时添加防御性回退样式（h1-h4/p/ul/ol/li/blockquote）防止插件加载失败时完全无样式。
- **DAG 节点消失**：四个改动联合修复 — (1) `handleEvent` 加事件白名单守卫，tool_call/llm_request 等无关 SSE 事件不再触发 `setNodeStates`，减少约 70% 无效 re-render；(2) `dag-canvas.tsx` 使用 `useRef` 缓存每个 node 的 data 对象，仅在 status/message/duration_ms 实际变化时创建新引用，使 `DagNode` 的 `React.memo` 真正跳过未变化节点的渲染；(3) 移除 ReactFlow 的 `fitView` prop，消除流式更新时的视口跳动；改为 `defaultViewport` 静态定位；(4) `setHasReroute` 从 `setNodeStates` updater 内部移到外部，消除 React 反模式。
- **报告样式**：移除 `report-viewer.tsx` 外层 `text-sm`（不再压制标题字号）；修复 `h2` 自定义组件的 `className` 合并逻辑（原来直接覆盖导致 prose 插件生成的字号/粗细/边距丢失）。

#### 修改的文件

- `frontend/package.json` — 新增 `@tailwindcss/typography` 依赖
- `frontend/app/globals.css` — 注册 `@plugin "@tailwindcss/typography"`；新增防御性 prose 回退样式
- `frontend/app/workflows/[id]/page.tsx` — `handleEvent` 加事件白名单、`setHasReroute` 移出 updater
- `frontend/components/dag/dag-canvas.tsx` — 新增 `useRef` data 缓存、移除 `fitView`、添加 `defaultViewport`
- `frontend/components/dag/dag-node.tsx` — 导出 `DagNodeData` 接口
- `frontend/components/report/report-viewer.tsx` — 移除 `text-sm`、修复 `h2` className 合并

#### 可能的潜在问题

- **data 缓存未检查 onRetry**：当前 `DagCanvas` 的父组件未传递 `onRetry` prop，缓存比较仅检查 status/message/duration_ms。若后续接入 onRetry 功能，缓存需增加对 onRetry 引用变化的感知（或改用 `useCallback` 稳定化）
- **prose 回退样式优先级**：防御性回退样式以 `.prose` 前缀写在全局 CSS 中，优先级低于 typography 插件生成的 utility class。但若插件版本升级导致选择器变化，回退样式可能意外生效并与插件样式叠加，需在升级后验证

---

### 10. DAG 运行时节点流式输出面板

DAG 执行期间，各 agent 通过 `LLM_STREAM` 事件广播逐 token 输出，前端新增独立面板实时显示当前活跃节点的 LLM 生成内容。同时保留用户对话框，支持在执行过程中输入反馈。

#### 修复方案

- **流式 token 累积**：新增 `useNodeStream` hook，内部用 `useRef` 按 `node_name` 缓冲 token，以 `requestAnimationFrame` + 64ms 间隔批量刷新到 state（~15fps），避免 per-token 渲染导致 ReactFlow 画布抖动。
- **LLM_STREAM 事件与 DAG 状态隔离**：`handleEvent` 中 `llm_stream` 事件在生命周期守卫之前处理，直接写入 token buffer 而不触发 `setNodeStates`，确保流式输出不会重新渲染 ReactFlow 节点。
- **右侧面板改为 Tab 切换**：原 EventConsole 独占的 400px 右侧面板拆分为 "Live Stream"（实时显示当前节点 LLM 输出 + 闪烁光标）和 "Events"（结构化事件日志）两个 tab。
- **用户对话框**：DAG 画布底部新增输入栏，支持 Enter 发送 / Shift+Enter 换行，消息显示在历史区。为后续人在回路实时打断功能预留交互基础。
- **`node_start` 切换时自动清空上一节点的流式文本**，`StreamPanel` 显示当前活跃节点名称和实时脉冲指示器。

#### 新增文件

- `frontend/lib/use-node-stream.ts` — token 缓冲 + rAF 批量渲染 hook
- `frontend/components/events/stream-panel.tsx` — 节点流式输出展示面板

#### 修改的文件

- `frontend/types/event.ts` — `EventType` 新增 `"llm_stream"`
- `frontend/app/workflows/[id]/page.tsx` — `DagRuntimeView` 集成 `useNodeStream` + `StreamPanel` + 对话框；`handleEvent` 增加 `llm_stream` 和 `node_start` 流式处理分支

#### 可能的潜在问题

- **历史回放无流式内容**：`LLM_STREAM` 事件不写数据库（避免 token 粒度 IO），因此页面刷新后通过 `/events` 回放历史时没有流式文本，Stream 面板为空。后续可在 `node_complete` 事件的 payload 中附带完整输出文本作为回放数据源
- **rAF 在后台 tab 暂停**：浏览器在非活跃 tab 中会暂停 `requestAnimationFrame`，导致 token 积累在 buffer 中不刷新。切回 tab 时一次性吐出大量文本。当前 `scheduleFlush` 的 fallback 路径在 rAF 未触发时通过 `elapsed >= 64ms` 判断直接 flush，但若 rAF 长时间不触发则无此路径。实际影响较小——用户看不到页面时本就不需要流畅渲染

---

### 11. 修复 DAG 人工跳转死循环 + 移除前端 Events 面板

#### 修复方案

- **collection 死循环**：`human_decision` 通过 `Command(update=...)` 注入 state 后在 resume 路径中从未被清除。Review 节点的 router 正确消费 `human_decision` 跳转到目标节点（如 collection），但目标节点执行完毕后其 router 再次看到同一 `human_decision`，又跳回同一目标节点，形成无限循环。修复方式：`make_pause_router` 中人工 jump 分支从 `return target`（纯字符串）改为 `return Command(goto=target, update={"human_decision": None})`，在消费决策的同时清除之，后续节点的 router 不再看到已消费的决策。
- **Events 面板移除**：`DagRuntimeView` 将全部 17 种 SSE 事件无上限累积在 `events: WorkflowEvent[]` 中，每个事件到达触触发 `EventConsole` 全量 `.filter().map()` 重渲染，`llm_stream` 等高频事件加剧性能问题。修复：移除 `events` state、`rightTab` 切换逻辑、`EventConsole` 组件及其文件，右侧面板固定显示 `StreamPanel`（LLM 流式输出）。历史事件回放 `useEffect` 仅重建 `nodeStates` 不再存储事件数组。node 状态更新和流式 token 处理不受影响。

#### 修改的文件

- `backend/app/core/orchestrator.py` — 新增 `from langgraph.types import Command`；`make_pause_router` 人工 jump 分支返回 `Command(goto=target, update={"human_decision": None})`
- `frontend/app/workflows/[id]/page.tsx` — 移除 `events`/`rightTab` state 及 `setEvents` 调用；右侧面板从 tab 切换改为固定 `StreamPanel`；历史回放仅重建 `nodeStates`；移除 `EventConsole` 导入
- `frontend/components/events/event-console.tsx` — 删除

#### 删除的文件

- `frontend/components/events/event-console.tsx` — Events 面板组件（功能已被 StreamPanel 替代，不再需要）

---

### 12. 修复 Interview 配置完成检测不可靠

Interview 阶段 LLM 输出 `---CONFIG_COMPLETE---` 后，前端有时无法跳转到 ready 状态，Start 按钮始终不出现。

#### 修复方案

- **后端 JSON 提取增强**：`try_extract_config` 先剥离 markdown 代码围栏（`` ```json ... ``` `` 或 ` ``` ... ``` `）再尝试 `find/rfind` 花括号匹配。LLM 经常用围栏包裹 JSON，原逻辑直接 `find("{")` 会在围栏内部的 JSON 前后留下 ` ``` ` 残片导致 `json.loads` 失败。
- **前端解耦 is_complete 与 extracted_config**：`onConfig` 仅处理配置数据更新，不再兼管完成信号；`onComplete` 从空函数改为直接设置 `isComplete(true)`。原逻辑要求 `is_complete && extracted_config` 同时为真才锁定配置，当后端提取失败发送 `extracted_config: null` 时永远无法完成。
- **安全网回拉**：`isComplete` 变为 true 时自动 fetch workflow API 拉取后端已持久化的 config，兜底覆盖极端情况。
- **空数组守卫**：`suggested_competitors` 检查加 `.length > 0`，空数组不再触发无意义的 setConfig。

#### 修改的文件

- `backend/app/agents/interview_agent.py` — `try_extract_config` 增加 markdown 围栏剥离策略；抽取 `_parse_json_block` helper
- `frontend/app/workflows/[id]/page.tsx` — `onConfig` 移除 `is_complete` 检查；`onComplete` 设置 `isComplete`；`suggested_competitors` 空数组守卫；新增安全网 `useEffect`

---

### 13. 工作流重进入健壮性 — 状态检测与恢复

用户重新打开工作流时，前端应根据当前状态主动跳转到正确界面。修复了 4 个阻碍重进入的关键问题。

#### 修复方案

- **"paused" 状态前端支持**：`WorkflowStatus` 类型、`statusLabel`/`statusColor` 新增 `"paused"` 条目；路由分支 `(status === "running" || status === "paused")` → `DagRuntimeView`；暂停时显示暂停卡片（暂停原因 + 操作按钮）。
- **对话框接线 /decide 端点**：暂停卡片中的按钮调用 `POST /{id}/decide`，传递 `action`/`target_node`/`feedback`。支持 `jump`（重试指定节点）、`approve`（强制通过）、`abort`（放弃）三种决策。决策提交后显示系统消息确认。
- **事件类型统一**：`EventType` 新增 `"reroute"` 和 `"workflow_resumed"`；`handleEvent` 和 historical replay 同时处理 `"reroute"` 和 `"review_reroute"` 两种事件名，解决后端 resume 路径发送 `EventType.REROUTE` 而前端只识别 `"review_reroute"` 的 mismtach。
- **事件回放增强**：历史事件请求升级为 `?limit=200`（此前依赖后端默认 50 条），避免长工作流事件被截断。
- **僵死工作流检测**：进入 RUNNING 工作流且历史事件重放后，若所有节点状态均为 idle 且最新事件超过 60 秒，判定为僵死工作流（服务重启导致进程丢失），展示警告提示用户返回仪表板重新启动。

#### 修改的文件

- `frontend/types/workflow.ts` — `WorkflowStatus` 新增 `"paused"`；`WorkflowDetail` 新增 `pause_state` 字段类型
- `frontend/types/event.ts` — `EventType` 新增 `"reroute"` 和 `"workflow_resumed"`
- `frontend/lib/utils.ts` — `statusLabel` 新增 `paused: "已暂停"`；`statusColor` 新增 amber 主题暂停色
- `frontend/app/workflows/[id]/page.tsx` — 路由支持 `paused`/`cancelled`；`DagRuntimeView` 接收 `workflow` prop；暂停卡片 UI + `/decide` 接线；事件类型 `reroute` 处理；事件回放 `limit=200`；僵死检测 + 警告提示

#### 可能的潜在问题

- **僵死检测仅前端**：服务重启后僵死工作流仅前端展示警告，无后端自动恢复机制。后续可在后端增加启动时扫描 `running` 工作流并按 checkpoint 自动 resume 的逻辑。
- **/decide 成功后的 UI 刷新**：决策提交后通过 SSE `workflow_resumed` / `node_start` 事件驱动 UI 更新，而非主动刷新 workflow 查询。若 SSE 连接延迟，暂停卡片可能短暂保持显示。后续可加 `router.refresh()` 强制刷新。

---

### 14. 修复 CHANGELOG #13 未生效 + Interview 配置健壮性 + 多项 latent bug

#### 修复方案

第 13 条添加的工作流重进入恢复机制**完全未生效**——根因是前后端契约不一致：后端 `GET /events` 返回 `{items, total, limit, offset}` 分页信封，前端假设是裸数组，`Array.isArray(body) === false` 直接 early-return，整段历史回放代码（包括 nodeStates 重建与僵死检测）都是死代码。本条同时修复了 interview 配置流的多个结构性问题，并清理了 CHANGELOG #8 / #12 留下的 latent bug。

**Section A — 前端恢复机制**

- **`/events` 响应形状兼容**：`DagRuntimeView` 的 replay `useEffect` 接受 `{items}` 信封与裸数组两种形状，兼容现有后端契约并对未来改动免疫。**这是让 #13 真正生效的关键 fix**。
- **InterviewView 重进入水合**：将 `config` / `isComplete` 从 `useState({})` 改为 `useState(() => fromWorkflow(workflow.config))` 懒初始化，重新打开工作流时右侧面板立即恢复已收集字段；若 `target_product + product_category` 均已存在则视为"可直接启动"，无需用户重新发送一条访谈消息触发 META。
- **解锁 isComplete 后的输入框**：textarea / send 按钮 disabled 条件从 `isComplete || isStreaming` 改为仅 `isStreaming`；`sendUserMessage` guard 同步去掉 `isComplete` 检查；`ConfigPanel` 新增"继续编辑访谈" ghost 按钮，让用户在配置不满意时仍能继续修订。
- **路由 switch 补齐 `created` + 未知 status fallback**：`created` 视为 configuring 入口；`workflow == null` 渲染"工作流不存在"卡片；未知 status 渲染调试卡片 + 刷新按钮（避免任何 enum 演进时出现整页空白）。
- **`handleDecide` 失效 workflow 查询**：成功路径后调用 `qc.invalidateQueries({queryKey: ["workflow", id]})`，approve→ReportView / jump→running view 切换不再依赖 SSE 到达。
- **ReportView token 一致性**：3 处 `localStorage.getItem("access_token")` 替换为 `useAuth().token`，与 InterviewView / DagRuntimeView 对齐，登出/换 token 时不会读到过期凭证。`ReportView` 内部对 `/events` 端点的另一次调用同步接受 `{items}` 信封。

**Section B — Interview 配置可靠性**

- **`/start` 错误内联回显**：`handleStart` 用 try/catch 捕获，提取 `response.data.detail` 渲染为 rose 色提示（之前完全静默）。配置编辑时自动清空错误。
- **本地 canStart 校验 gate**：`Boolean(target_product && product_category)` 才允许点击 Start。按钮 disabled 时提示"请先补全产品名称和品类"。
- **`/start` 接受可选 config body**（前后端）：`useStartWorkflow.mutationFn` 改为 `({id, config})`，POST body 为完整 `WorkflowConfig`；后端 `start_workflow_endpoint` 接受可选 `WorkflowConfig | None = Body(default=None)`，service 层在状态校验前用其覆盖 `workflow.config`（`flag_modified` 标记 JSON 列变更）。**让右侧面板用户编辑成为权威配置**，即使 LLM 完全未提取 JSON 也能启动。`ConfigPanel` Start 渲染条件从 `isComplete` 放宽为 `isComplete || canStart`，允许无 sentinel 也可启动。

**Section C — Latent bug 与其他优化**

- **`pause_state.dag_state` 持久化（修 CHANGELOG #8 的死代码）**：`workflow_executor.py` 两处持久化点（run_workflow + resume_workflow）都加上 `dag_state: pause_data.get("dag_state", {})`。原代码显式丢弃这个字段但 `resume_workflow:205-206` 又试图从中读 `review_result`，使 `cached_review_result` 永远为 None——CHANGELOG #8 的"跳过 review LLM 重跑"优化是死代码。同时修了 `resume_workflow` 在清空 `pause_state` **之前**就读 `dag_state` 的顺序——之前因为 `pause_state = None` 已经先执行，`dag_state` 永远是 `{}`（即使 C1 持久化也读不到）。现在引入 `dag_state_before` / `paused_by_node_before` 快照变量，在 commit 前抓取。
- **running 状态 polling 兜底**：`useWorkflow` 新增 `refetchInterval: (q) => q.state.data?.status === "running" ? 15_000 : false` + `refetchOnWindowFocus: true`。SSE 丢失 `workflow_complete` 时 15s 内仍能切到 ReportView，终态自动停止轮询。
- **`WorkflowDetail` 类型对齐后端**：移除从未填充的 `progress`（含 `phases.collecting` 等死字段）和 `PhaseStatus`；新增 `max_revisions`、`total_tokens`、`error_message`、`completed_at`、`pause_state.dag_state`；`config` 类型放宽为 `Partial<WorkflowConfig>` 反映 JSON 列可能为部分配置的现实。
- **`try_extract_config` 平衡括号扫描**：`_parse_json_block` 的 `find("{")` + `rfind("}")` 在 LLM 回复中含对话性大括号（如 `{user_name}`、模板占位符）时会跨越正确的 JSON 边界，导致 `json.loads` 失败。新增 `_iter_balanced_json_blocks` 工具方法，逐字符维护括号深度计数器（正确处理字符串字面量与转义），yield 所有顶层 `{...}` 子串；`try_extract_config` 优先 markdown fence，否则取**最后一个**通过 Pydantic 校验的 block（LLM 通常先草拟再给最终配置）。

#### 修改的文件

- `frontend/app/workflows/[id]/page.tsx` — A1/A2/A3/A4/A5/A6/B1/B2/B3
- `frontend/components/interview/config-panel.tsx` — 新增 `canStart` / `startError` / `onResumeEditing` props；Start gating 改为 `(isComplete || canStart)`；新增 caption 与"继续编辑访谈" ghost 按钮；inline 错误回显
- `frontend/lib/use-workflow.ts` — `useStartWorkflow.mutationFn` 改为 `({id, config})`；`useWorkflow` 新增 `refetchInterval` / `refetchOnWindowFocus`
- `frontend/types/workflow.ts` — 移除 `PhaseStatus` 与 `WorkflowDetail.progress`，补齐 `max_revisions`/`total_tokens`/`error_message`/`completed_at`/`pause_state.dag_state`
- `backend/app/api/v1/workflow.py` — `start_workflow_endpoint` 接受可选 `WorkflowConfig | None = Body(default=None)`
- `backend/app/services/workflow_service.py` — `start_workflow` 增加 `override_config` 形参，使用 `flag_modified` 标记 JSON 列变更
- `backend/app/core/workflow_executor.py` — 两处 `pause_state` 持久化点新增 `dag_state` 字段；`resume_workflow` 在 commit 前快照 `dag_state_before` / `paused_by_node_before`
- `backend/app/agents/interview_agent.py` — 新增 `_iter_balanced_json_blocks`；`_parse_json_block` 与 `try_extract_config` 重写采用平衡扫描 + Pydantic 校验

#### 可能的潜在问题

- **InterviewView 懒水合不响应 server.config 更新**：另一个 tab 完成访谈后回到本 tab，新的 `workflow.config` 不会被本 tab 拿来覆盖本地状态。这是有意设计（保护用户编辑），但若两个 tab 同时操作可能出现配置漂移。后续可加版本号 / mtime 检测，或在 useWorkflow 刷新时显式提示用户合并。
- **handleDecide 后立即 invalidate 可能撞上后端事务延迟**：jump 路径是 BG task，invalidate 触发的 refetch 可能仍读到 `status=paused`，UI 短暂停留在暂停卡片。SSE 到达后自然刷新。可接受。
- **`pause_state.dag_state` 可能撑大 JSON 列**：当前 `_sanitize_for_json` 已剥离 `messages`，但 `raw_data`（采集到的搜索原文）会一并写入。PostgreSQL JSON 列单行无硬上限但查询会变慢。后续可在 sanitize 中再去掉 `raw_data` 字段，仅保留 review/report 结构化结果。
- **`try_extract_config` 取最后一个有效 block 的策略可能误判**：若 LLM 在确认配置后又继续输出其他不相关 JSON（罕见），会取后者。`---CONFIG_COMPLETE---` 哨兵 + markdown fence 优先策略仍是首选保护层。
- **`override_config` 信任前端**：前端可发任意合法 `WorkflowConfig` 覆盖访谈结果。当前权限模型下用户只能操作自己的 workflow，影响可控；后续若引入团队/审批流需要重新评估。

