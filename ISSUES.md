# 已知问题 / Known Issues

> 最后更新：2025-05-25
> 本文件记录了代码审查中发现但尚未修复的问题。已修复项见 [CHANGELOG.md](./CHANGELOG.md)。

---

## Bug

### 1. 已完成的工作流无法删除
- **文件**: [backend/app/api/v1/workflow.py](backend/app/api/v1/workflow.py#L79)
- **严重程度**: 中
- **描述**: `delete_workflow_endpoint` 先调用 `cancel_workflow` 再调用 `delete_workflow`。`cancel_workflow` 在状态为 `"completed"` 或 `"cancelled"` 时抛出 `InvalidStateTransitionError`，阻止删除执行。
- **修复方向**: 删除端点不应无条件调用 cancel；改为仅在非终态时 cancel，终态直接 delete。

### 2. 重试端点忽略 `node_name` 参数
- **文件**: [backend/app/api/v1/workflow.py](backend/app/api/v1/workflow.py#L84-L102)
- **严重程度**: 中
- **描述**: `POST /{workflow_id}/retry/{node_name}` 接收了 `node_name` 但从未传给 `run_workflow`，重试永远从 DAG 起点 `information_collection` 重新执行。
- **修复方向**: 利用 LangGraph checkpoint 从失败节点恢复，或至少在 initial state 中传入起始节点。

### 3. `datetime.utcnow()` 产生无时区 datetime
- **文件**: [common.py](backend/app/schemas/common.py#L16), [competitor.py](backend/app/schemas/competitor.py#L19), [report_agent.py](backend/app/agents/report_agent.py#L30)
- **严重程度**: 低
- **描述**: 三处使用 `datetime.utcnow()` 返回 naive datetime，Python 官方建议替换为 `datetime.now(timezone.utc)`。
- **修复方向**: 全局替换 `datetime.utcnow()` → `datetime.now(timezone.utc)`。

### 4. 服务重启后产生僵尸 "running" 工作流
- **文件**: [backend/app/core/workflow_executor.py](backend/app/core/workflow_executor.py)
- **严重程度**: 高
- **描述**: `run_workflow` 运行在 FastAPI `BackgroundTasks` 中，服务进程挂掉后 workflow 行永久卡在 `"running"`。无启动恢复、心跳或超时检测机制。
- **修复方向**: 添加启动时扫描 `status=running` 的 workflow 并标记为 `failed`；或引入心跳 + 超时自动失败。

---

## 设计问题

### 5. Config 在访谈流中被静默整体覆盖
- **文件**: [backend/app/services/interview_service.py](backend/app/services/interview_service.py#L81-L87)
- **严重程度**: 低
- **描述**: `workflow.config = config.model_dump()` 直接替换整个 config 对象，如果之前有额外字段会静默丢失。
- **修复方向**: 改为 `workflow.config = {**workflow.config, **config.model_dump()}` merge 策略。

### 6. CORS origin 硬编码
- **文件**: [backend/app/main.py](backend/app/main.py#L27)
- **严重程度**: 低
- **描述**: CORS `allow_origins` 硬编码为 `["http://localhost:3000"]`，非本地部署需要改代码。
- **修复方向**: 移到 Settings 配置项，通过环境变量控制。

### 7. SSEManager broadcast 被慢客户端阻塞
- **文件**: [backend/app/services/sse_service.py](backend/app/services/sse_service.py#L36-L38)
- **严重程度**: 低
- **描述**: `broadcast` 对每个订阅者顺序 `await queue.put()`，一个慢消费者会阻塞所有其他订阅者。
- **修复方向**: 改用 `put_nowait()` + 丢弃满队列消费者，或用 `asyncio.gather` 并行推送。

### 8. 数据库连接池未调优
- **文件**: [backend/app/db/session.py](backend/app/db/session.py#L6)
- **严重程度**: 低
- **描述**: 使用默认连接池配置（`pool_size=5`, `max_overflow=10`），工作流执行期间 LLM 调用可能耗时数分钟，并发下容易耗尽。
- **修复方向**: 添加 `pool_size` / `max_overflow` / `pool_recycle` 配置项。

### 9. ORM 模型未定义 `relationship()`
- **文件**: 全部 `backend/app/db/models/*.py`
- **严重程度**: 低
- **描述**: `Workflow` 与子表（`Artifact`, `WorkflowEvent`, `WorkflowNodeState` 等）之间无 ORM 级 relationship，无法 eager loading，应用层感知不到关联。
- **修复方向**: 按需添加 `relationship()` 定义。

---

## 2025-05-25（初次审查）

以上为初次代码审查的完整发现。同时修复的 5 个问题（模块级副作用、JWT 默认密钥、Query param 改 Body、密码校验、频率限制）见 [CHANGELOG.md](./CHANGELOG.md)。
