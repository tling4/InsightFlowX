# InsightFlowX

AI 驱动的竞品分析多 Agent 协作系统。

通过 LangGraph 编排多个专业 Agent，自动完成信息采集、多维分析、报告撰写和质量审查，帮助产品经理回答一个核心问题：

> **这对我到底有什么用？**

---

## 目录

1. [项目概述](#1-项目概述)
2. [核心功能](#2-核心功能)
3. [项目结构](#3-项目结构)
4. [关键业务逻辑](#4-关键业务逻辑)
5. [创新点](#5-创新点)
6. [运行](#6-运行)

---

## 1. 项目概述

### 1.1 背景与定位

传统竞品分析容易停留在"信息罗列"层面——别人做了什么、有哪些功能、宣传了什么卖点。但对产品经理来说，真正重要的不是信息本身，而是：

1. 我要解决的问题是什么
2. 哪些信息对解决这个问题真正有用
3. 这些信息是否来自可信来源
4. 对方成功或失败的原因到底是什么
5. 最终能给当前项目带来什么可执行结论

因此，DAGents-InsightFlow 的目标不是生成一份"更长的竞品报告"，而是帮助用户围绕明确问题，输出可参考、可验证、可决策的分析结论。

### 1.2 适用场景

- **没思路时找参考**：想知道别人是怎么做的，快速找到当前阶段可借鉴的较优解
- **有方向时找证据**：已有判断，需要真实案例和来源来验证想法、说服团队
- **需要落地结论时做取舍**：不想陷入信息堆积，希望最终输出能服务具体项目决策

### 1.3 产品方法论

项目默认遵循三步竞品分析框架：

- **定义**：先定义目标问题与竞品范围，解决"分析谁"的问题。竞品分为五类——核心竞品、标杆竞品、潜力竞品、替代竞品、避坑竞品
- **拆解**：围绕目标问题，拆解竞品在产品定位、功能、定价、用户情感、上市增长等维度的关键动作与结果
- **结论**：输出可执行的判断，明确"我们该借鉴什么、验证什么、避免什么"

### 1.4 技术栈

| 层 | 技术 |
|---|------|
| **后端框架** | FastAPI（异步 HTTP + SSE 流式推送） |
| **Agent 编排** | LangGraph StateGraph（DAG 节点编排 + 条件路由 + Checkpoint 持久化） |
| **LLM** | 火山方舟（字节豆包），OpenAI 兼容接口 |
| **搜索** | Tavily API（竞品信息搜索、竞品发现、页面提取） |
| **数据库** | PostgreSQL 14+（asyncpg 业务查询 + psycopg Checkpoint） |
| **ORM** | SQLAlchemy 2.0 async |
| **认证** | JWT + bcrypt |
| **可观测性** | LangSmith（LLM 调用全链路追踪） |

---

## 2. 核心功能

### 2.1 已实现功能清单

**用户与认证**

- 用户注册/登录（bcrypt 密码哈希 + JWT 认证，24h 过期）
- API 限流（登录 10 次/min/IP，注册 5 次/min/IP）

<img src="images/注册.png" width="80%">

<img src="images/登录.png" width="80%">


**工作流管理**

- 工作流 CRUD（创建、列表、详情、更新标题、删除）
- 完整生命周期状态机：`created → configuring → running → completed/failed/cancelled`
- 执行批次管理（`execution_attempt` 递增，`WorkflowRun` 运行实例隔离）

**访谈配置（Pre-DAG）**

- `InterviewAgent` 多轮 SSE 流式对话，引导用户确定目标产品、竞品范围、分析维度
- 自动提取 `WorkflowConfig`（含产品画像、竞品分组、搜索计划）
- Tavily 自动推荐竞品（竞品实体消歧 + 分类策略匹配 smartphone/drone/SaaS）
- 智能完成检测——识别用户确认信号，自动判定访谈结束

<img src="images/配置确认.png" width="80%">

**DAG 工作流执行**

- 10 节点 LangGraph StateGraph 编排（见 [4.1 节](#41-dag-工作流拓扑)）
- `BackgroundTasks` 异步执行（无 Celery 依赖）
- Postgres Checkpoint 持久化（`thread_id = "{workflow_id}:{run_id}"`，支持崩溃恢复）
- 节点指数退避重试（最多 3 次，5 分钟超时，`GraphInterrupt` 不重试直接传播）

<img src="images/运行1.png" width="80%">

**信息采集**

- 多竞品并发搜索（`asyncio.gather`，单个竞品失败不阻断其他竞品）
- 领域感知搜索查询计划生成（LLM 驱动 + 确定性回退，确保关键意图覆盖）
- URL 去重与相关性过滤、覆盖率检查与恢复查询
- 搜索结果上下文压缩（截断 + 意图多样性选择）

**多维分析**

- SWOT 分析（各竞品优劣势、机会与威胁）
- 功能对比矩阵（按维度生成，支持差异描述和证据引用）
- 定价方案对比（含计费周期、定价模型）
- 用户情感聚合分析（正面/负面/中性 + 共性赞扬/抱怨）
- 产品定位五维度拆解（用户/场景/问题/解决方案/支撑点）
- 竞品角色判定（五分类 + 置信度 + 证据）
- 上市与增长策略拆解（节奏/预算/平台/内容/投放/结果 6 维度）

**报告撰写**

- 三批次结构化生成：分析批次 → 决策批次 → 补充批次
- 严格章节校验（标题精确匹配、禁止标题语法出现在正文）
- Mermaid 流程图（关键流程可视化）
- 内联引用列表与来源回溯

<img src="images/结构化看板1.png" width="80%">
<img src="images/分析报告1.png" width="80%">

**质量审查**

- LLM + 规则双路径：四维审查（completeness / accuracy / consistency / credibility）
- 硬性门禁：竞品有效性 + 来源覆盖率（覆盖 LLM 结果）
- 失败分类：transient_failure / structural_coverage_gap / artifact_inconsistency / report_render_issue
- 审查不通过自动路由至目标节点重做（最多 3 轮修订）

**Human-in-the-Loop**

- 审查未通过时自动暂停，生成 `PauseRequest`（含原因、选项、建议路由）
- 6 种决策动作：jump / approve / abort / drop_competitor / keep_with_insufficient_evidence / replace_competitor
- 支持崩溃恢复（`/recover` 端点，从 LangGraph Checkpoint 恢复僵尸工作流）

<img src="images/暂停.png" width="80%">

**可观测性**

- 事件日志系统（每个事件独立 commit，`seq` 单调递增，`run_id` 维度隔离，27 种事件类型）
- SSE 实时推送（`asyncio.Queue` 广播节点进度 + LLM token 流）
- 节点状态快照（完整 state 持久化，自动剔除 messages/raw_data 大字段）
- 产物存储（JSON 结构化数据 + Markdown 文本，支持下载）
- 溯源链接（每条分析断言 → 原始 URL + 置信度评分）

**Windows 兼容**

- `psycopg` 在 Windows 非 reload 模式下自动切换 `SelectorEventLoop` 线程完成连接握手
- `app/__init__.py` 预置 `WindowsSelectorEventLoopPolicy` 策略

### 2.2 API 端点汇总

| 分组 | 方法 | 路径 | 说明 |
|------|------|------|------|
| Auth | POST | `/api/v1/auth/register` | 用户注册 |
| Auth | POST | `/api/v1/auth/login` | 登录，返回 JWT |
| Auth | GET | `/api/v1/auth/me` | 当前用户信息 |
| Workflow | POST | `/api/v1/workflows` | 创建工作流 |
| Workflow | GET | `/api/v1/workflows` | 工作流列表 |
| Workflow | GET | `/api/v1/workflows/{id}` | 工作流详情 |
| Workflow | PATCH | `/api/v1/workflows/{id}` | 更新标题 |
| Workflow | DELETE | `/api/v1/workflows/{id}` | 删除工作流 |
| Workflow | POST | `/api/v1/workflows/{id}/start` | 确认配置，启动 DAG |
| Workflow | POST | `/api/v1/workflows/{id}/retry/{node}` | 重新执行 |
| Workflow | POST | `/api/v1/workflows/{id}/recover` | 崩溃恢复 |
| Workflow | POST | `/api/v1/workflows/{id}/decide` | 人工决策 |
| Interview | POST | `/api/v1/workflows/{id}/interview/stream` | SSE 流式访谈 |
| Interview | GET | `/api/v1/workflows/{id}/interview/history` | 访谈历史 |
| Interview | POST | `/api/v1/workflows/{id}/interview/confirm` | 确认配置 |
| Event | GET | `/api/v1/workflows/{id}/events` | 事件列表（分页+筛选） |
| Event | GET | `/api/v1/workflows/{id}/stream` | SSE 实时事件流 |
| Event | GET | `/api/v1/workflows/{id}/states` | 节点状态快照 |
| Artifact | GET | `/api/v1/workflows/{id}/artifacts` | 产物列表 |
| Artifact | GET | `/api/v1/artifacts/{id}` | 产物详情 |
| Artifact | GET | `/api/v1/artifacts/{id}/download` | 下载 Markdown 报告 |
| Trace | GET | `/api/v1/workflows/{id}/trace` | 溯源链接列表 |

### 2.3 测试覆盖

**101 个测试全部通过**，覆盖以下维度：

- Runtime 模板结构与策略决策
- Human-in-the-Loop 完整流程（Pause → Decide → Resume → Reroute）
- 所有 Agent 进度事件与结构化输出
- 竞品实体消歧（smartphone / drone / SaaS 策略）
- 报告三批次生成 + 章节校验 + Mermaid 验证
- 异常类 + API 错误响应（401/404/400/409/500）
- 认证 + 工作流 + 访谈 API 集成

---

## 3. 项目结构

```
DAGents-InsightFlow/
│
├── backend/
│   ├── app/
│   │   ├── __init__.py                     # Windows SelectorEventLoop 策略预设
│   │   ├── main.py                         # FastAPI 入口：lifespan（建表 + checkpointer）+ CORS + 异常处理
│   │   ├── config.py                       # pydantic-settings：从 .env 加载全局配置
│   │   ├── dependencies.py                 # FastAPI Depends：JWT 解码 → current_user
│   │   ├── exceptions.py                   # 业务异常层级（AppException + 7 子类）
│   │   │
│   │   ├── api/v1/                         # ── HTTP 接口层 ──
│   │   │   ├── router.py                   #   路由聚合，挂载 6 个子路由到 /api/v1
│   │   │   ├── auth.py                     #   注册 / 登录 / 当前用户（含限流）
│   │   │   ├── workflow.py                 #   工作流 CRUD + start / retry / recover / decide
│   │   │   ├── interview.py                #   访谈 SSE 流 + 历史 + 配置确认
│   │   │   ├── event.py                    #   事件分页查询 + SSE 实时流 + 快照历史
│   │   │   ├── artifact.py                 #   产物列表 / 详情 / Markdown 下载
│   │   │   └── trace.py                    #   溯源链接查询
│   │   │
│   │   ├── core/                           # ── 核心编排层 ──
│   │   │   ├── runtime/                    #   ★ 声明式多 Agent 编排 Runtime
│   │   │   │   ├── template.py             #     GraphTemplate / NodeSpec / RetryPolicy
│   │   │   │   │                           #     PauseRequest / ControlDecision / ArtifactDraft
│   │   │   │   ├── context.py              #     AgentContext / EventSink（Agent 唯一运行时入口）
│   │   │   │   ├── node_runner.py          #     NodeRunner：执行 + 重试 + 快照 + 产物
│   │   │   │   ├── graph_runtime.py        #     GraphRuntime：编译 StateGraph + ainvoke/aresume/arecover
│   │   │   │   ├── policies.py             #     DefaultRoutePolicy / ReviewRoutePolicy / ReviewFailPausePolicy
│   │   │   │   └── retry.py                #     execute_with_retry（指数退避）+ NodeFatalError
│   │   │   ├── competitive_template.py     #   竞品分析 10 节点业务模板实例化
│   │   │   ├── workflow_executor.py        #   run / resume / recover 工作流编排入口
│   │   │   ├── pause_service.py            #   Pause 提取 / 持久化 / 解析 + interrupt payload 构建
│   │   │   └── dependency/
│   │   │       ├── checkpointer.py         #     AsyncPostgresSaver 生命周期（含 Windows 兼容处理）
│   │   │       └── langsmith.py            #     LangSmith 环境变量早启动注入
│   │   │
│   │   ├── agents/                         # ── Agent 层 ──
│   │   │   ├── base_agent.py               #   BaseAgent：emit_progress / stream_llm_token / invoke_llm / invoke_structured_llm
│   │   │   ├── interview_agent.py          #   多轮访谈对话 + 配置提取（pre-DAG）
│   │   │   ├── collection_agent.py         #   竞品解析 + 搜索计划 + 并发采集 + 去重 + 覆盖率检查
│   │   │   ├── analysis_agent.py           #   SWOT + 6 子分析（feature/pricing/sentiment/positioning/role/gtm）
│   │   │   ├── report_agent.py             #   三批次结构化报告 + 严格章节校验 + Mermaid 流程图
│   │   │   ├── review_agent.py             #   LLM 审查 + 规则门禁 + 失败分类 + 重试价值判断
│   │   │   ├── agent_utils.py              #   LLM JSON 提取/Schema 修复/证据归一化/上下文压缩
│   │   │   ├── competitor_resolver.py      #   竞品实体消歧与补充（多品类策略）
│   │   │   ├── product_profiler.py         #   目标产品画像推断
│   │   │   └── query_planner.py            #   搜索查询计划生成（LLM + 确定性回退）
│   │   │
│   │   ├── schemas/                        # ── 数据模型层 ──
│   │   │   ├── runtime_state.py            #   RuntimeState {data, control, runtime, errors}
│   │   │   ├── workflow_state.py           #   WorkflowState 别名
│   │   │   ├── workflow.py                 #   WorkflowConfig / ProductProfile / CompetitorGroups
│   │   │   ├── event.py                    #   EventType 枚举（27 种）+ 各事件 payload 模型
│   │   │   ├── decision.py                 #   DecisionAction / DecisionRequest
│   │   │   ├── interview.py / report.py / review.py
│   │   │   ├── competitor.py / competitor_role.py / evidence.py
│   │   │   ├── feature.py / pricing.py / sentiment.py / swot.py
│   │   │   ├── positioning.py / gtm.py / search.py
│   │   │   ├── common.py / auth.py
│   │   │   └── __init__.py
│   │   │
│   │   ├── services/                       # ── 服务层 ──
│   │   │   ├── workflow_service.py         #   工作流 CRUD + 状态转换 + 标题推断
│   │   │   ├── interview_service.py        #   访谈 6 阶段流式处理 + 竞品推荐 + 智能完成检测
│   │   │   ├── event_service.py            #   EventLogger（共享 seq 计数器 + asyncio.Lock）
│   │   │   ├── sse_service.py              #   SSEManager（asyncio.Queue 广播）
│   │   │   ├── auth_service.py             #   bcrypt 密码 + JWT 签发/验证
│   │   │   └── rate_limiter.py             #   内存滑动窗口限流
│   │   │
│   │   └── db/                             # ── 数据持久层 ──
│   │       ├── base.py                     #   SQLAlchemy DeclarativeBase
│   │       ├── session.py                  #   异步引擎 + session factory + get_async_session 依赖
│   │       ├── models/                     #   10 个 ORM 模型（见 4.3 节数据库设计）
│   │       └── queries/                    #   数据查询辅助函数
│   │
│   ├── tests/                              # ── 测试（101 个用例）──
│   │   ├── conftest.py                     #   SQLite 内存 DB + 限流器禁用夹具
│   │   ├── test_human_in_the_loop.py       #   ★ 最大测试文件（1181 行）
│   │   ├── test_runtime_template.py        #   模板结构 + 策略决策
│   │   ├── test_analysis_agent.py          #   SWOT + 子节点 + LLM 回退
│   │   ├── test_report_agent.py            #   三批次生成 + 章节/Mermaid 验证
│   │   ├── test_collection_agent.py        #   采集进度 + 无 Tavily 回退
│   │   ├── test_competitor_resolver.py     #   竞品消歧（多品类策略）
│   │   ├── test_node_progress.py           #   EventSink + 所有 Agent 进度事件
│   │   ├── test_agent_utils.py             #   JSON 提取 / Schema 修复 / 归一化
│   │   ├── test_exceptions.py              #   异常类 + API 错误响应
│   │   ├── test_interview_service.py       #   访谈响应 + 配置提取
│   │   ├── test_workflow_executor.py       #   interrupt payload + pause state
│   │   └── test_api/                       #   API 集成测试（auth / workflow / interview）
│   │
│   ├── alembic/                            # 数据库迁移
│   ├── migrations/                         # 手动 SQL 迁移脚本
│   ├── pyproject.toml                      # Python 项目配置 + 依赖声明
│   ├── pytest.ini                          # asyncio_mode = auto
│   ├── .env.example                        # 环境变量模板
│   └── .env                                # 实际环境变量（gitignore）
│
└── README.md                               # 本文件
```

---

## 4. 关键业务逻辑

### 4.1 DAG 工作流拓扑

系统使用 LangGraph StateGraph 构建 10 节点线性 DAG，`review` 节点支持条件回跳：

```
information_collection     ← 竞品解析 + 搜索查询计划 + 并发采集 + 去重
        │
   analysis (SWOT)         ← 各竞品优劣势/机会/威胁
        │
   feature_analysis        ← 功能对比矩阵（按维度）
        │
   pricing_analysis        ← 定价方案对比（含计费周期/模型）
        │
   sentiment_analysis      ← 用户情感聚合（正面/负面/共性）
        │
   positioning_analysis    ← 产品定位五维度拆解
        │
   role_analysis           ← 竞品角色判定（五分类 + 置信度）
        │
   gtm_analysis            ← 上市增长策略（6 维度）
        │
   report_writing          ← 三批次结构化报告 + 引用 + Mermaid
        │
      review               ← LLM + 规则双路径审查
        │
   ┌────┴────┐
 通过      未通过
   │         │
 完成     revision < 3?
           │      │
          是     否
           │      │
       ┌───┴───┐ 完成
     暂停     自动打回
  (人工决策)  (路由至目标节点)
```

**关键设计**：

- 所有节点通过 `allowed_routes` 允许被 review 回跳至任意前序节点
- 只有 `review` 节点配置了 `PausePolicy`（`ReviewFailPausePolicy`）和 `RoutePolicy`（`ReviewRoutePolicy`）
- 其他节点使用 `DefaultRoutePolicy` 线性前进
- 6 个子分析节点（feature → gtm）**共用同一个 `AnalysisAgent` 实例**，通过 `ctx.node_id` 区分执行逻辑

### 4.2 工作流生命周期

```
POST /workflows          POST /start              BackgroundTasks
      │                      │                        │
      ▼                      ▼                        ▼
  created ──→ configuring ──→ running ──→ DAG 执行 ──→ completed
                 │                          │    │
                 │                          │    ├──→ failed
            InterviewAgent              pause │    │
            (SSE 多轮对话)                    ▼    └──→ cancelled
                                        paused ──→ /decide
                                                   │
                                    approve/abort/jump/...
```

1. **create** → 状态 `created`，等待访谈
2. **interview** → 状态 `configuring`，SSE 多轮对话确定 `WorkflowConfig`
3. **start** → 状态 `running`，`BackgroundTasks` 启动 DAG
4. **DAG 执行** → 10 节点依次执行，`review` 可能触发暂停或打回
5. **complete/fail/cancel** → 终态

### 4.3 Runtime 抽象层设计

项目的核心架构创新是一套**声明式多 Agent 编排 Runtime**，将业务逻辑与执行基础设施完全解耦。

**三区分离的 RuntimeState**：

```python
RuntimeState = {
    "data":    {...},   # 业务数据（config, raw_data, feature_matrix, report...）
    "control": {...},   # 运行控制（current_node, route_label, revision_count...）
    "runtime": {...},   # 实例元信息（workflow_id, run_id, thread_id, execution_attempt）
    "errors":  [...],   # 错误历史
}
```

- `data`：只由 Agent 读写，Runtime 只透传
- `control`：只由 Runtime / ControlGate / Policy 读写，Agent 不可见
- `runtime`：初始化后不可变，记录运行实例标识

**声明式 NodeSpec**：

```python
NodeSpec(
    id="review",
    agent=ReviewAgent(),
    default_next="done",
    allowed_routes=REROUTE_TARGETS,
    retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
    pause_policy=ReviewFailPausePolicy(),
    route_policy=ReviewRoutePolicy(),
    artifact_factory=_report_artifacts,
)
```

每个 `NodeSpec` 被 `GraphRuntime` 编译为**两个 LangGraph 节点**：`{id}`（业务节点）+ `{id}__gate`（控制门）。Gate 节点统一处理暂停判断 → 路由决策 → 结束/跳转。

**Agent 统一接口**：

```python
async def run(self, state: dict, ctx: AgentContext) -> dict:
    """返回需要合并到 state.data 的增量字典"""
```

Agent 只能通过 `AgentContext` 访问运行时信息，不直接持有数据库连接、SSE 管理器或事件日志——这些由 Runtime 在 Agent 外部统一管理。

**新增节点的成本**：只需定义 Agent 类 + 在 `competitive_template.py` 中添加一个 `NodeSpec` 条目。不需要修改 Runtime、Executor、API 层的任何代码。

### 4.4 Human-in-the-Loop 机制

系统通过 LangGraph 的 `interrupt()` 机制实现人工决策点：

```
review 未通过
    │
    ▼
ReviewFailPausePolicy.build_pause()
    │  检查 review_result.passed + revision_count < max
    │  生成 PauseRequest {reason, options, suggested_route, context}
    ▼
ControlGate: interrupt(payload)
    │  LangGraph 暂停，checkpoint 持久化
    ▼
workflow.status = "paused"
workflow.pause_state = UI 元数据
workflow_pause 表写入
    │
    ▼
用户调用 POST /decide {action: "jump", target_node: "analysis"}
    │
    ▼
resume_workflow() → resolve pause → GraphRuntime.aresume(decision)
    │  将 ControlDecision 注入 control["human_decision"]
    ▼
ControlGate 恢复 → ReviewRoutePolicy.decide()
    │  读取 human_decision → 决定路由目标
    ▼
LangGraph conditional edge: 跳转至目标节点或结束
```

6 种决策动作：

| 动作 | 效果 |
|------|------|
| `jump` | 跳转至指定节点重做 |
| `approve` | 强制通过审查，完成工作流 |
| `abort` | 中止工作流 |
| `drop_competitor` | 移除问题竞品后继续（针对 structural_coverage_gap） |
| `keep_with_insufficient_evidence` | 标记证据不足但保留 |
| `replace_competitor` | 移除问题竞品并用 Tavily 推荐替代 |

### 4.5 信息采集策略

`CollectionAgent` 采用"先解析、再计划、后采集"三步策略：

1. **竞品解析**：验证用户提供的竞品名有效性 → Tavily 搜索补充 → 实体消歧（按品类匹配 smartphone/drone/SaaS 策略）
2. **查询计划生成**：LLM 生成 `SearchQueryPlan`（含 `{product}` 占位符的意图感知查询模板）→ 确定性回退确保覆盖 overview / official / independent_evidence / 用户关注维度
3. **并发采集**：`asyncio.gather(*tasks, return_exceptions=True)` 并发执行所有竞品 × 所有查询，单竞品失败不阻断其他竞品；最少 6 条来源/竞品，不达标触发恢复查询

### 4.6 报告生成策略

`ReportAgent` 采用三批次结构化生成，避免单次 LLM 调用输出过长导致质量下降：

- **分析批次**（5 章节）：分析目标、产品定位判断、竞品角色判断、关键发现、成功与失败原因
- **决策批次**（3 章节 + 摘要）：结论先行、对当前项目的启示、行动建议 + 报告标题 + 执行摘要
- **补充批次**（2 章节）：上市与增长拆解、关键流程图（Mermaid）

严格校验：章节标题精确匹配、禁止 `#`/`##` 出现在正文内容中、Mermaid 代码块完整性检查。

### 4.7 质量审查策略

`ReviewAgent` 采用 LLM + 规则双路径：

**LLM 审查**：四维评分（completeness 35% + accuracy 35% + consistency 15% + credibility 15%），passed = score ≥ 70 且所有关键检查通过

**硬性门禁**（覆盖 LLM 结果）：

- 竞品有效性：报告中引用的竞品必须存在于 WorkflowConfig
- 来源覆盖率：关键结论必须有原始来源支撑

**失败分类**：

| 分类 | 含义 | 处理建议 |
|------|------|---------|
| `transient_failure` | 临时数据缺失 | 自动重试可能修复 |
| `structural_coverage_gap` | 结构性问题 | 需删除/替换竞品 |
| `artifact_inconsistency` | 分析产物不一致 | 打回目标分析节点 |
| `report_render_issue` | 报告渲染问题 | 打回 report_writing |

### 4.8 数据库设计

```
user 1──N workflow 1──N interview_message
                    │
                    │ 1──N workflow_run          ← 运行实例隔离
                    │ 1──N workflow_pause        ← 暂停请求与决策
                    │ 1──N workflow_event        ← 事件日志（27 种事件类型）
                    │ 1──N workflow_node_state   ← 节点执行快照
                    │ 1──N artifact              ← 结构化产物 + Markdown 文本
                    │       │
                    │       └──N trace_link      ← 结论 → 来源 URL 溯源
                    │
                    └── (search_template)        ← 按品类搜索策略预设
```

**关键表设计要点**：

| 表 | 关键设计 |
|---|---------|
| `workflow` | JSONB config、current_run_id 关联活跃运行实例、execution_attempt 递增、pause_state 暂停元信息 |
| `workflow_run` | thread_id = "{workflow_id}:{run_id}" 映射 LangGraph checkpoint |
| `workflow_pause` | reason + options(JSON) + context(JSON) + decision(JSON)，完整记录暂停-决策闭环 |
| `workflow_event` | 独立行写入 + 立即 commit、seq 单调递增（asyncio.Lock）、run_id 隔离 |
| `workflow_node_state` | state_snapshot 自动剔除 messages/raw_data 大字段、tokens_input/output 用量记录 |
| `artifact` | content(JSONB) + content_text(Text) 双存储、format_version 版本管理 |
| `trace_link` | section_path 精确定位、confidence 评分、is_verified 标记 |

---

## 5. 创新点

### 5.1 声明式多 Agent 编排 Runtime

当前 LangGraph 生态中，多数项目将 Agent 逻辑、暂停/路由/重试策略与 LangGraph 节点代码耦合在一起。本项目的 Runtime 抽象层将这三者彻底分离：

- **业务 Agent** 只实现 `run(state, ctx) -> dict`，不感知编排逻辑
- **NodeSpec** 声明式定义每个节点的 agent、路由策略、暂停策略、重试策略、产物工厂
- **GraphRuntime** 自动编译为 LangGraph StateGraph + 注入 ControlGate
- **Policy** 可插拔（`DefaultRoutePolicy` / `ReviewRoutePolicy` / 自定义策略）

这使得新增一个带复杂暂停-决策-路由逻辑的节点，成本降低到只需定义一个 `NodeSpec` 条目。

### 5.2 三区分离的 RuntimeState

将 LangGraph 的单一 State 字典按职责拆分为 `data` / `control` / `runtime` 三区：

- Agent 无法写入 `control` 区，从架构层面预防了"Agent 错误地修改运行控制状态"的问题
- `runtime` 区不可变，保证运行实例标识的一致性
- `data` 区由 Agent 自由读写，保持业务灵活性

### 5.3 审查驱动的细粒度回退

不同于常见的"审查不通过→整个 DAG 重跑"，本项目的 Review 机制支持：

- **节点级回退**：可精确打回至 information_collection / analysis / 任意子分析节点 / report_writing
- **子节点感知**：AnalysisAgent 通过 `ctx.node_id` 识别当前执行的是哪个子分析，`_should_rerun_subnode()` 判断是否需要重跑
- **失败分类**：区分 transient_failure / structural_coverage_gap / artifact_inconsistency / report_render_issue，为后续 P2 阶段"局部回退不重跑全局"提供基础

### 5.4 竞品实体消歧与领域感知搜索

`CompetitorResolver` 不是简单地用关键词搜 Tavily，而是：

- 按产品品类匹配策略（smartphone/drone/SaaS/generic），每种策略有独立的正则模式、有效提示词和无效关键词列表
- 检测乱码、非产品短语、同系列变体、品类描述词等无效名称
- 结合 LLM 产品画像推断 + Tavily 搜索补充，自动发现用户未指定的相关竞品

### 5.5 结构化证据归一化

`EvidenceRef` 将 LLM 输出中常见的"只给 URL 字符串"归一化为结构化证据对象（url + title + snippet + source_type + confidence + captured_at），为后续 P1 Artifact-First 阶段"所有关键结论绑定证据"提供统一的证据抽象。

### 5.6 三批次报告生成与严格校验

不同于一次 LLM 调用生成整份报告，`ReportAgent` 分为三个独立批次：

- 每批次有独立 prompt 和输出 schema
- 分析批次聚焦"有哪些发现"，决策批次聚焦"对我有什么用"，补充批次聚焦"可视化呈现"
- 组装后通过严格校验（标题精确匹配、禁止标题语法泄漏、Mermaid 完整性）

这降低了单次 LLM 调用的上下文压力，也使得未来 P3 "报告渲染化"阶段可以独立替换每个批次的生成逻辑。

---

## 6. 运行

### 6.1 环境要求

- Python 3.11+
- PostgreSQL 14+

### 6.2 后端启动

```bash
# 1. 进入后端目录
cd backend

# 2. 创建虚拟环境并激活
python -m venv .venv
.venv\Scripts\activate     # Windows
# source .venv/bin/activate  # Linux/Mac

# 3. 安装依赖
pip install -e .

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 LLM API Key、Tavily API Key、数据库连接信息
```

**.env 关键配置项**：

```bash
# 数据库
DATABASE_URL=postgresql+asyncpg://postgres:your-password@127.0.0.1:5432/dagents
DATABASE_URL_SYNC=postgresql://postgres:your-password@127.0.0.1:5432/dagents

# LLM（火山方舟，OpenAI 兼容接口）
LLM_API_KEY=your-llm-api-key
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3/
LLM_MODEL=your-llm-model-name

# 搜索
TAVILY_API_KEY=your-tavily-api-key

# JWT
JWT_SECRET_KEY=your-jwt-secret-key

# LangSmith（可选，LLM 调用追踪）
LANGSMITH_TRACING_V2=true
LANGSMITH_API_KEY=your-langsmith-api-key
LANGSMITH_PROJECT=dagents-insightflow
```

```bash
# 5. 创建数据库
psql -U postgres -c "CREATE DATABASE dagents;"

# 6. 启动服务（首次启动自动建表）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

> **Windows 注意**：建议始终使用 `--reload`。非 reload 模式下 uvicorn 硬编码 `ProactorEventLoop`，系统已在 [checkpointer.py](backend/app/core/dependency/checkpointer.py) 中内置兼容处理。

### 6.3 访问 API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 6.4 运行测试

```bash
cd backend
pip install pytest pytest-asyncio httpx aiosqlite

# 全部测试
python -m pytest -v

# 按模块运行
python -m pytest tests/test_human_in_the_loop.py -v
python -m pytest tests/test_runtime_template.py -v
python -m pytest tests/test_analysis_agent.py -v
python -m pytest tests/test_api/ -v
```

当前状态：**101 个测试全部通过**。测试使用 SQLite 内存数据库，无需 PostgreSQL。

### 6.5 快速验证流程

```bash
# 1. 注册用户
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "demo", "email": "demo@test.com", "password": "demo123456"}'

# 2. 登录获取 token
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "demo@test.com", "password": "demo123456"}'

# 3. 创建工作流
curl -X POST http://localhost:8000/api/v1/workflows \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"title": "分析英雄牌钢笔的竞品"}'

# 4. 进行访谈（SSE 流式）
curl -X POST http://localhost:8000/api/v1/workflows/<workflow_id>/interview/stream \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"user_message": "从价格、质量、供应链三个方面分析英雄牌钢笔和竞品"}'

# 5. 确认配置并启动
curl -X POST http://localhost:8000/api/v1/workflows/<workflow_id>/start \
  -H "Authorization: Bearer <token>"

# 6. 查看事件进度
curl http://localhost:8000/api/v1/workflows/<workflow_id>/events \
  -H "Authorization: Bearer <token>"

# 7. 下载报告
curl http://localhost:8000/api/v1/artifacts/<artifact_id>/download \
  -H "Authorization: Bearer <token>" \
  -o report.md
```

### 6.6 后续迭代方向

- **P1 — Artifact First**：结构化 artifact 升级为核心产物，Markdown 降为展示层，所有关键结论绑定 EvidenceRef
- **P2 — 分析层拆分**：6 个子分析模块独立契约 + 局部回退，当前 10 节点 DAG 已为此提供架构支撑
- **P3 — 报告渲染化**：ReportAgent 职责收缩为"组织 artifact → 渲染章节"，证据状态可视化
- **P4 — 智能补救**：自动别名扩展、实体消歧、缺源判定、部分完成机制

---

## License

MIT
