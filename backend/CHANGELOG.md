# Changelog

## 2026-05-25

### 全局异常处理架构

引入 Java Spring `@ExceptionHandler` 风格的全局异常处理机制，替换原有的 `return None` + 手动 `HTTPException` 模式。

**新增文件：**

- `app/exceptions.py` — 业务异常层级：`AppException` 基类 + 7 个子类（`WorkflowNotFoundError`、`InvalidStateTransitionError`、`ConfigIncompleteError`、`InvalidCredentialsError`、`InvalidTokenError`、`DuplicateResourceError`、`ArtifactNotFoundError`），每个携带 `error_code` / `message` / `status_code` / `details`

**修改文件：**

- `app/main.py` — 注册两个全局 handler：`AppException` → 结构化 JSON 响应；`Exception` → 500 兜底 `{"error_code": "INTERNAL_ERROR"}`
- `app/services/workflow_service.py` — `return None` 替换为 `raise` 对应异常
- `app/services/auth_service.py` — `authenticate_user` 返回 None 改为 `raise InvalidCredentialsError`
- `app/dependencies.py` — 4 处 `raise HTTPException(401)` 替换为 `raise InvalidTokenError`
- `app/api/v1/*.py` — 移除 `HTTPException` 导入，手动 `raise HTTPException(404)` 替换为 `WorkflowNotFoundError` / `ArtifactNotFoundError` 等

### 结构化错误记录

- `app/core/workflow_executor.py` — 新增 `_extract_error_info()` 解包 `NodeFatalError.last_error` 获取 `AppException` 的结构化字段，`WORKFLOW_FAILED` event payload 包含 `error_code` / `error_message` / `error_details`
- `app/core/node_executor.py` — `NODE_ERROR` event payload 使用业务 `error_code`（内层为 `AppException` 时）
- `app/core/graph_nodes.py` — 抽取 `_execute_node()` 公共 helper，统一在 `NodeFatalError` 时保存 `WorkflowNodeState` 并标记 `is_error=True`，修复 `is_error` 列从未被使用的死字段

### 查询层重构

将分散在各 service 和 API 路由中的 15 处 SQLAlchemy 内联查询抽取到 `app/db/queries/` 目录，按业务域分文件：

- `user_queries.py` — `get_user_by_email`、`get_user_by_username`、`get_user_by_id`
- `workflow_queries.py` — `get_workflow_by_id`、`get_workflow_by_uuid`、`get_user_workflows`、`get_message_history`
- `event_queries.py` — `get_events`、`count_events`、`get_node_states`
- `artifact_queries.py` — `get_workflow_artifacts`、`get_artifact_by_id`、`get_artifact_ids_by_workflow`、`get_trace_links`

### 测试

- `tests/conftest.py` — 异步 TestClient 基础设施，SQLite in-memory 数据库，依赖覆盖
- `tests/test_exceptions.py` — 18 个测试：13 个单元测试验证异常类构造，5 个集成测试验证 API 错误响应形状（401/404/409/400/500）
- `tests/test_api/` — 原有 6 个 API 测试（auth、workflow、interview）全部通过

### 杂项修复

- `app/api/v1/workflow.py` — 补充缺失的 `Depends` 导入
- `app/api/v1/event.py` — 移除未使用的 `HTTPException` 导入
