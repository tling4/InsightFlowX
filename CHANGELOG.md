# Changelog

## 2025-05-25

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
