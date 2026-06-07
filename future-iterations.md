# DAGents-InsightFlow 后续迭代路线图

本文档用于沉淀当前项目下一阶段的核心重构方向，重点解决三个结构性问题：

- 当前系统仍然把 `Markdown` 报告当作事实主产物，导致 `review` 和 `report` 容易互相污染。
- `analysis` 仍偏向一次性大包生成，缺乏更细粒度的 artifact 与回退机制。
- 系统在缺源、实体不清、局部失败时的自救能力还不够强，仍然需要较多人工介入。

后续迭代的总方向是：

- 升级为 `Artifact-First` 架构。
- 让 `Markdown` 从“主产物”降为“展示层”。
- 让 `review` 审结构化 artifact，而不是主要审最终文案。
- 让运行时支持更细粒度的分析、回退、补救和渲染。

---

## P1 Artifact First

### 目标

把结构化 artifact 升级为系统核心产物，让所有关键判断先落在 artifact，再由报告层消费和组织。

### 主要改动

#### 1. Artifact 升级为核心产物

- `Markdown` 不再是事实主存储。
- 所有关键结论、比较、角色判断、证据引用，先写入结构化 artifact。
- 报告只负责把 artifact 组织成可读形式。

#### 2. FeatureMatrix 升级

从当前的：

```python
feature_name + products: dict[str, str]
```

升级为支持二维矩阵能力的结构，至少支持：

- 模块
- 支持程度
- 差异描述
- 证据引用

建议方向：

```python
FeatureMatrixArtifact {
  rows: [
    {
      module: "...",
      capability: "...",
      comparisons: [
        {
          product: "...",
          support_level: "...",
          difference_summary: "...",
          evidence_refs: [...]
        }
      ]
    }
  ]
}
```

#### 3. PricingComparison 升级

在现有结构基础上增加：

- `raw_price`
- `currency`
- `billing_period`
- `pricing_model`
- `evidence_refs`

避免价格分析只剩“总结性文字”，无法回溯到真实来源。

#### 4. EvidenceRef 统一抽象

建立统一证据对象，所有关键结论都通过 `EvidenceRef` 关联来源。

每条证据至少挂：

- `url`
- `title`
- `snippet`
- `source_type`
- `confidence`
- `captured_at`

建议方向：

```python
EvidenceRef {
  url: str
  title: str
  snippet: str
  source_type: str
  confidence: float
  captured_at: datetime
}
```

#### 5. CompetitorRoleAnalysis 标准化

将当前“附加分析结果”升级为标准 artifact。

至少支持：

- 角色
- 理由
- 证据
- 置信度

建议方向：

```python
CompetitorRoleAnalysisArtifact {
  items: [
    {
      product: "...",
      role: "core|benchmark|potential|substitute|pitfall|unknown",
      reason: "...",
      evidence_refs: [...],
      confidence: 0.0
    }
  ]
}
```

#### 6. ReviewAgent 改为审 Artifact

`ReviewAgent` 不再主要检查：

- Markdown 是否够长
- 章节是否够多
- 表达是否像一份完整报告

改为主要审：

- 哪个 artifact 缺字段
- 哪条结论缺 evidence
- 哪个竞品覆盖不足
- 哪个分析模块不可信

### 验收标准

- `review` 失败时，能定位到具体 artifact 字段或具体竞品。
- 报告中的大多数关键结论，都能反查到对应 evidence。
- `Markdown` 报告不再承担“事实真相”的职责。

---

## P2 分析层拆分

### 目标

把当前“一次性大包分析”拆成多个子任务或子 artifact，让分析层支持局部成功、局部失败和局部回退。

### 主要改动

#### 1. AnalysisAgent 拆解

从当前“一次性大包生成”，拆成多个独立分析模块或子 artifact：

- `feature_analysis`
- `pricing_analysis`
- `sentiment_analysis`
- `positioning_analysis`
- `competitor_role_analysis`
- `gtm_analysis`

每个模块都应该有独立输入契约、独立输出 artifact、独立 review 粒度。

#### 2. GraphTemplate 支持更细粒度回退

`review` 不再只会把问题打回整个 `analysis` 节点。

应支持只回退到：

- `feature`
- `pricing`
- `sentiment`
- `role`
- `report_render`

而不是整段 `analysis` 全量重跑。

#### 3. Collection -> Analysis 数据契约收紧

明确每个分析模块需要什么最低输入。

例如：

- `pricing_analysis` 需要明确价格页或价格证据
- `sentiment_analysis` 需要用户评价类来源
- `role_analysis` 需要竞品边界和分类判断证据

同时支持：

- 部分模块成功
- 部分模块标记证据不足
- 部分模块跳过但不阻断全局

### 验收标准

- 当只有定价数据缺失时，不需要重跑整个分析。
- 当角色判断不稳定时，只重做角色分析，不影响功能矩阵和报告正文。
- 分析模块之间的污染明显下降。

---

## P3 报告渲染化

### 目标

收缩 `ReportAgent` 的职责，让它从“生成事实”变成“组织 artifact 为可读报告”。

### 主要改动

#### 1. ReportAgent 职责收缩

从：

- 生成事实
- 自由发挥组织逻辑
- 自己补很多解释性结论

改成：

- 读取 artifact
- 组织 artifact
- 渲染成章节化报告

#### 2. 报告章节与 artifact 对齐

每个章节优先映射一个或多个明确 artifact。

例如：

- 产品定位判断 -> `positioning_analysis`
- 功能对比 -> `feature_analysis`
- 定价分析 -> `pricing_analysis`
- 角色判断 -> `competitor_role_analysis`
- 上市与增长拆解 -> `gtm_analysis`

降低 `ReportAgent` 的自由发挥空间。

#### 3. 章节级 evidence 绑定

报告里的关键结论需要显示：

- evidence 来源
- evidence 状态
- 证据不足提示

让用户在报告层就能知道：

- 这条结论是否可信
- 这条结论依据什么
- 这条结论是不是只是方向性判断

### 验收标准

- 报告与 artifact 不一致的概率明显下降。
- `review` 不再因为“报告自己长歪了”而误判采集/分析失败。
- 报告从“自由生成文本”转向“artifact 渲染结果”。

---

## P4 智能补救

### 目标

在缺源、实体不清或局部失败时，系统先自救，再请求用户介入。

### 主要改动

#### 1. CollectionAgent 搜索策略升级

增加以下能力：

- 自动别名扩展
- 英文名 / 品牌名 / 系列名变体
- 实体消歧
- 更宽 / 更窄 query 回退

提升冷门竞品、歧义实体和不稳定来源场景下的召回和命中率。

#### 2. 缺源自动判定

系统自动区分：

- 临时抓取失败
- 结构性公开资料不足

避免把所有问题都一律打回“继续重试采集”。

#### 3. 部分完成机制

允许系统输出：

- 已确认结论
- 待确认结论
- 证据不足结论

不要因为局部证据不足就让整份分析完全失败。

### 验收标准

- 用户介入次数下降。
- 缺源时系统先自救，再请求用户决策。
- 系统能更明确地区分“现在该自动补救”还是“现在该暂停给用户决定”。

---

## 依赖关系

建议按以下顺序推进：

1. `P1 Artifact First`
2. `P2 分析层拆分`
3. `P3 报告渲染化`
4. `P4 智能补救`

原因：

- 如果没有 `Artifact-First`，后面的 review、回退和渲染都会继续被 Markdown 绑架。
- 如果分析层不拆分，runtime 就无法做真正细粒度回退。
- 如果报告不收缩职责，review 仍然会把“渲染问题”误判成“采集问题”。
- 智能补救应建立在更清晰的数据契约和 review 粒度之上。

---

## 最终目标

这一轮后续迭代的最终目标不是把报告写得更长，而是把系统升级为：

- 以 artifact 为核心真相
- 以 evidence 为统一支撑
- 以 review 为结构化审查
- 以 runtime 为细粒度回退执行器
- 以 report 为可视化展示层

最终让系统真正回答：

- 哪些结论已经被证据支持
- 哪些结论仍然不稳定
- 哪些模块可以局部重做
- 哪些信息值得进入最终决策
