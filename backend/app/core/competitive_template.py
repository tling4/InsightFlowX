"""竞品分析工作流的图模板定义。

本模块将竞品分析的四个 agent（Collection / Analysis / Report / Review）
组装为声明式 GraphTemplate，并定义各阶段所需的制品工厂和初始数据工厂。

图拓扑（线性 DAG，review 节点支持条件回跳）:

    information_collection ──→ analysis ──→ report_writing ──→ review ──→ done
         │                        │              │                │
         │                        │              │         （未通过时回跳到
         │                        │              │          任何允许的节点）
         │                        │              │
         产出: collection_raw     产出:           产出: report
                                feature_matrix
                                pricing_comparison
                                user_sentiment
                                swot_analysis

所有节点都通过 allowed_routes=REROUTE_TARGETS 允许被 review 回跳，
但只有 review 节点配置了可触发 reroute 的策略（ReviewRoutePolicy +
ReviewFailPausePolicy）。其他节点使用 DefaultRoutePolicy 线性前进。
"""

from __future__ import annotations

from app.agents.analysis_agent import AnalysisAgent
from app.agents.collection_agent import CollectionAgent
from app.agents.report_agent import ReportAgent
from app.agents.review_agent import ReviewAgent
from app.core.runtime.policies import DefaultRoutePolicy, ReviewFailPausePolicy, ReviewRoutePolicy
from app.core.runtime.template import ArtifactDraft, GraphTemplate, NodeSpec, RetryPolicy

# review 不通过时可回跳的目标节点集合
REROUTE_TARGETS = ("information_collection", "analysis", "report_writing")

# 单例 agent 实例（无状态，复用）
_collection_agent = CollectionAgent()
_analysis_agent = AnalysisAgent()
_report_agent = ReportAgent()
_review_agent = ReviewAgent()


def _collection_artifacts(patch: dict, data: dict) -> list[ArtifactDraft]:
    """信息采集阶段制品工厂 —— 提取 raw_data 存入 collection_raw 制品。"""
    raw_data = patch.get("raw_data")
    if not raw_data:
        return []
    return [
        ArtifactDraft(
            artifact_type="collection_raw",
            title="采集原始数据",
            content=raw_data,
            created_by_node="information_collection",
        )
    ]


def _analysis_artifacts(patch: dict, data: dict) -> list[ArtifactDraft]:
    """分析阶段制品工厂 —— 从 patch 中提取四类分析结果并分别持久化。"""
    config = data.get("config", {}) if isinstance(data.get("config"), dict) else {}
    target = config.get("target_product", "")
    artifacts: list[ArtifactDraft] = []
    for artifact_type, key in [
        ("feature_matrix", "feature_matrix"),
        ("pricing_comparison", "pricing_comparison"),
        ("user_sentiment", "user_sentiment"),
        ("swot_analysis", "swot"),
    ]:
        content = patch.get(key)
        if content is not None:
            artifacts.append(
                ArtifactDraft(
                    artifact_type=artifact_type,
                    title=f"{target} {artifact_type}",
                    content=content,
                    created_by_node="analysis",
                )
            )
    return artifacts


def _report_artifacts(patch: dict, data: dict) -> list[ArtifactDraft]:
    """报告阶段制品工厂 —— 提取报告 dict 及其 Markdown 纯文本版本。"""
    report = patch.get("report")
    if not report:
        return []
    title = report.get("title", "竞品分析报告") if isinstance(report, dict) else "竞品分析报告"
    markdown = report.get("full_markdown", "") if isinstance(report, dict) else ""
    return [
        ArtifactDraft(
            artifact_type="report",
            title=title,
            content=report,
            content_text=markdown,
            created_by_node="report_writing",
        )
    ]


def make_initial_data(workflow) -> dict:
    """构建竞品分析工作流的初始 data dict。

    GraphRuntime.initial_state() 会从这个 dict 中提取 revision_count / max_revisions
    到 control 层，其余字段保留在 data 层供 agent 使用。

    Args:
        workflow: Workflow ORM 对象（含 config 和 max_revisions）
    Returns:
        完整的初始 data 字典
    """
    return {
        "config": workflow.config,
        "competitors": [],
        "raw_data": {},
        "collection_errors": {},
        "context_summaries": {},
        "feature_matrix": None,
        "pricing_comparison": None,
        "user_sentiment": None,
        "swot": None,
        "report": None,
        "review_result": None,
        "revision_count": 0,
        "max_revisions": workflow.max_revisions,
        "current_phase": "collecting",
        "workflow_status": "running",
        "errors": [],
        "messages": [],
    }


# ── 图模板定义 ──────────────────────────────────────────────────────────

CompetitiveAnalysisTemplate = GraphTemplate(
    name="competitive_analysis",
    entrypoint="information_collection",
    nodes=(
        NodeSpec(
            id="information_collection",
            agent=_collection_agent,
            default_next="analysis",
            allowed_routes=REROUTE_TARGETS,
            retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
            route_policy=DefaultRoutePolicy(),
            artifact_factory=_collection_artifacts,
        ),
        NodeSpec(
            id="analysis",
            agent=_analysis_agent,
            default_next="report_writing",
            allowed_routes=REROUTE_TARGETS,
            retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
            route_policy=DefaultRoutePolicy(),
            artifact_factory=_analysis_artifacts,
        ),
        NodeSpec(
            id="report_writing",
            agent=_report_agent,
            default_next="review",
            allowed_routes=REROUTE_TARGETS,
            retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
            route_policy=DefaultRoutePolicy(),
            artifact_factory=_report_artifacts,
        ),
        NodeSpec(
            id="review",
            agent=_review_agent,
            default_next="done",
            allowed_routes=REROUTE_TARGETS,
            retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
            pause_policy=ReviewFailPausePolicy(),
            route_policy=ReviewRoutePolicy(),
        ),
    ),
)
