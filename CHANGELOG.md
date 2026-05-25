# Changelog

## 2025-05-25

### 增加全局异常处理架构

引入 Java Spring `@ExceptionHandler` 风格的全局异常处理机制，替换原有的 `return None` + 手动 `HTTPException` 模式。

#### 新增文件

- `app/exceptions.py` — 业务异常层级：`AppException` 基类 + 7 个子类（`WorkflowNotFoundError`、`InvalidStateTransitionError`、`ConfigIncompleteError`、`InvalidCredentialsError`、`InvalidTokenError`、`DuplicateResourceError`、`ArtifactNotFoundError`），每个携带 `error_code` / `message` / `status_code` / `details`

#### 修改的文件

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

### 修复安全与运行问题

- **模块级副作用改为懒初始化** ([#5]): `interview_service.py` 中 `tavily_client` 和 `interview_agent` 从模块导入时实例化改为首次调用时懒初始化，避免 API key 为空或 LLM 配置错误时静默失败。
- **JWT 密钥强制显式配置** ([#6]): `JWT_SECRET_KEY` 移除不安全默认值 `"change-me-in-production"`，未配置时启动即报错而非静默使用弱密钥。
- **创建 Workflow 改用 JSON body** ([#7]): `POST /workflows` 的 `title` 参数从 query string 改为 JSON 请求体 (`WorkflowCreate` schema)，避免 title 暴露在 URL 和服务器日志中。
- **密码与用户名添加长度校验** ([#8]): `UserRegister.password` 要求 `min_length=8`，`username` 要求 `min_length=3`。
- **认证接口添加频率限制** ([#14]): 新增 `RateLimiter` 内存固定窗口实现，登录 10 次/60s，注册 5 次/60s，超限返回 429。

#### 修改的文件

| 文件 | 变更 |
|------|------|
| `backend/app/services/interview_service.py` | 懒初始化 `tavily_client` / `interview_agent`；`import json` 移至顶部 |
| `backend/app/config.py` | `JWT_SECRET_KEY` 移除默认值，强制配置 |
| `backend/app/schemas/workflow.py` | 新增 `WorkflowCreate` 请求体 schema |
| `backend/app/api/v1/workflow.py` | `create_new_workflow` 从 query param 改为 Body |
| `backend/app/schemas/auth.py` | `password` / `username` 添加 `min_length` 校验 |
| `backend/app/api/v1/auth.py` | `login` / `register` 添加 `Depends(rate_limit)` |
| `backend/app/services/rate_limiter.py` | 新增频率限制服务 |
| `backend/tests/conftest.py` | 添加 `JWT_SECRET_KEY` 测试默认值；覆盖 rate limiter 为 no-op |
| `backend/tests/test_api/*.py` | 更新密码长度和 JSON body 调用方式 |
| `backend/tests/test_exceptions.py` | 同步更新 |
