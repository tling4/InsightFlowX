# 已知问题 / Known Issues

> 最后更新：2026-06-02
> 本文件记录了代码审查中发现但尚未修复的问题。已修复项见 [CHANGELOG.md](./CHANGELOG.md)。

---

## Bug

### 1. 已完成的工作流无法删除
- **文件**: [backend/app/api/v1/workflow.py](backend/app/api/v1/workflow.py#L83-L92)
- **严重程度**: 高
- **描述**: `delete_workflow_endpoint` 先调用 `cancel_workflow` 再调用 `delete_workflow`。`cancel_workflow` 在状态为 `"completed"` 或 `"cancelled"` 时抛出 `InvalidStateTransitionError`，阻止删除执行。
- **修复方向**: 删除端点不应无条件调用 cancel；改为仅在非终态（`configuring` / `running` / `paused`）时 cancel，终态（`completed` / `cancelled` / `failed`）直接 delete。
- **修复代码**:
  ```python
  workflow = await get_workflow_by_id(db, workflow_id, current_user.id)
  if not workflow:
      raise WorkflowNotFoundError(workflow_id)
  if workflow.status not in ("completed", "cancelled", "failed"):
      await cancel_workflow(db, workflow_id, current_user.id)
  await delete_workflow(db, workflow_id, current_user.id)
2. 重试端点忽略 node_name 参数
文件: backend/app/api/v1/workflow.py
严重程度: 中
描述: POST /{workflow_id}/retry/{node_name} 接收了 node_name 但从未传给 run_workflow，重试永远从 DAG 起点 information_collection 重新执行。
修复方向: 利用 LangGraph checkpoint 从失败节点恢复（recover_workflow 已实现类似逻辑），或在 run_workflow 中接受起始节点参数。当前接口文档应明确标注"重试 = 从头重新执行"。
3. datetime.utcnow() 产生无时区 datetime
文件: collection_agent.py, report_agent.py 及 _insufficient_report / _fallback_report 中共 3 处
严重程度: 低
描述: 多处使用 datetime.utcnow() 返回 naive datetime，Python 官方建议替换为 datetime.now(timezone.utc)。
修复方向: 全局替换 datetime.utcnow() → datetime.now(timezone.utc)。
4. 服务重启后产生僵尸 "running" 工作流
文件: backend/app/core/workflow_executor.py, backend/app/main.py
严重程度: 高
描述: run_workflow 运行在 FastAPI BackgroundTasks 中，服务进程挂掉后 workflow 行永久卡在 "running"。无启动恢复、心跳或超时检测机制。recover_workflow 函数存在但从未在启动时自动调用。
修复方向: 在 lifespan() 中添加启动扫描逻辑：查询所有 status=running 的 workflow，若有有效 checkpoint 则触发 recover_workflow，否则标记为 failed。
修复代码:
# 在 main.py lifespan() 中 await init_checkpointer() 后追加：
asyncio.create_task(_recover_zombie_workflows())

async def _recover_zombie_workflows():
    from app.db.session import async_session_factory
    from app.db.models.workflow import Workflow
    from sqlalchemy import select
    async with async_session_factory() as db:
        result = await db.execute(select(Workflow).where(Workflow.status == "running"))
        for wf in result.scalars().all():
            wf.status = "failed"
            wf.error_message = "服务重启导致执行中断，请手动重试"
        await db.commit()
并发与一致性问题
5. 暂停恢复无并发保护（竞态条件）
文件: backend/app/core/workflow_executor.py, backend/app/api/v1/workflow.py
严重程度: 中
描述: resume_workflow 和 POST /decide 端点对 workflow.status 无乐观锁或分布式锁保护。两个并发 POST /decide 请求可能同时将 status 从 paused 改为 running 并各自触发 resume_workflow，导致 DAG 被重复执行。
修复方向: 在 resume_workflow 中先以 SELECT ... FOR UPDATE 锁定 workflow 行，再检查 status 是否为 paused；或在 API 层使用 CAS 更新（UPDATE ... SET status='running' WHERE id=? AND status='paused'），通过 affected rows 判断是否抢锁成功。
6. Checkpointer 与业务表不在同一事务
文件: backend/app/core/checkpointer.py
严重程度: 中
描述: AsyncPostgresSaver 使用独立的 psycopg.AsyncConnection（autocommit=True），与 SQLAlchemy 管理的业务表不在同一事务边界。极端情况下可能出现：(1) checkpoint 已保存但 workflow.status = "paused" 未提交；(2) 业务状态已提交但 checkpoint 丢失。
修复方向: 这是双轨持久化设计的根本限制。可通过以下方式降低风险：确保 interrupt() 内部先写 checkpoint，外层再 commit 业务状态（当前已部分实现）；resume 时对 checkpoint 缺失做容错处理。
7. _execute_node resume 路径对非 review 节点仍重跑 LLM
文件: backend/app/core/graph_nodes.py
严重程度: 低
描述: cached_review_result 跳过 LLM 重跑的优化仅覆盖 review 节点。当 human_decision 已在 state 中且 agent 再次返回 __pause__ 时，_execute_node 跳过 interrupt() 但仍使用 agent 的新返回值——agent 内部的 LLM 调用已重新执行。
修复方向: 当前只有 review 节点使用 __pause__，影响有限。若未来其他节点也引入 __pause__，需为对应节点添加类似 cached_review_result 的缓存跳过机制。
数据与性能问题
8. pause_state.dag_state 将 raw_data 写入 JSON 列导致膨胀
文件: backend/app/core/graph_nodes.py
严重程度: 中
描述: _sanitize_for_json 仅跳过 messages，但保留了 raw_data（Tavily 全部搜索结果原文）。单次采集的 raw_data 可达数百 KB 甚至 MB 级，写入 pause_state.dag_state 和 workflow_node_state.state_snapshot 的 JSON 列后显著撑大行体积，影响查询性能。
修复方向: 在 _sanitize_for_json 中同时跳过 raw_data 键：
_SKIP_KEYS = {"messages", "raw_data"}
resume 时 raw_data 仍可从 LangGraph checkpoint 中恢复（checkpoint 保存完整 state），不受影响。
9. SSEManager broadcast 被慢客户端阻塞
文件: backend/app/services/sse_service.py
严重程度: 低
描述: broadcast 对每个订阅者顺序 await queue.put()，一个慢消费者会阻塞所有其他订阅者。
修复方向: 改用 put_nowait() + 丢弃满队列消费者；asyncio.Queue 设置 maxsize=256。
修复代码:
def subscribe(self, workflow_id: uuid.UUID) -> asyncio.Queue:
    ...
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    ...

async def broadcast(self, workflow_id: uuid.UUID, event_data: dict) -> None:
    dead: list[asyncio.Queue] = []
    for queue in self._subscribers.get(workflow_id, []):
        try:
            queue.put_nowait(event_data)
        except asyncio.QueueFull:
            dead.append(queue)
    for queue in dead:
        self.unsubscribe(workflow_id, queue)
10. 数据库连接池未调优
文件: backend/app/db/session.py
严重程度: 低
描述: 使用默认连接池配置（pool_size=5, max_overflow=10），工作流执行期间 LLM 调用可能耗时数分钟，并发下容易耗尽。
修复方向: 添加 pool_size / max_overflow / pool_recycle 配置项，建议 pool_size=10, max_overflow=20, pool_recycle=300。
设计问题
11. Config 在访谈流中被静默整体覆盖
文件: backend/app/services/interview_service.py
严重程度: 低
描述: workflow.config = config.model_dump() 直接替换整个 config 对象，如果之前有额外字段会静默丢失。
修复方向: 改为 workflow.config = {**workflow.config, **config.model_dump()} merge 策略。
12. CORS origin 硬编码
文件: backend/app/main.py
严重程度: 低
描述: CORS allow_origins 硬编码为 ["http://localhost:3000"]，非本地部署需要改代码。
修复方向: 在 Settings 中新增 CORS_ORIGINS: str = "http://localhost:3000"，main.py 改为 [o.strip() for o in get_settings().CORS_ORIGINS.split(",")]。
13. ORM 模型未定义 relationship()
文件: 全部 backend/app/db/models/*.py
严重程度: 低
描述: Workflow 与子表（Artifact, WorkflowEvent, WorkflowNodeState 等）之间无 ORM 级 relationship，无法 eager loading，应用层感知不到关联。
修复方向: 按需添加 relationship() 定义，至少在 Workflow 上添加 events、artifacts、node_states relationship。
14. make_pause_router 的 agent 建议路径仅适用于 review 节点
文件: backend/app/core/orchestrator.py
严重程度: 低（当前仅 review 使用 __pause__，不影响功能）
描述: Router 仅在 current_node == "review" 时检查 review_result.target_node。若未来其他 agent（如 analysis、report）也返回 __pause__ 并建议 target_node，Router 不会响应。
修复方向: 为使用 __pause__ 的新 agent 在 Router 中添加对应的 state key 检查分支，或建立统一的"agent 建议"state 字段约定。
15. 重试端点的 node_name 参数未被利用
文件: backend/app/api/v1/workflow.py
严重程度: 低（功能正常但语义不准确）
描述: 与 Issue #2 同源。当前 retry 实质是"从头重新执行"而非"重试指定节点"，接口名称和参数有误导性。
修复方向: 短期方案——在 docstring 中明确说明当前行为；长期方案——结合 recover_workflow + checkpoint 实现真正的节点级重试。