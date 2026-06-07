"""竞品分析工作流的图模板定义。

本模块将竞品分析的四个 agent（Collection / Analysis / Report / Review）
组装为声明式 GraphTemplate，并定义各阶段所需的制品工厂和初始数据工厂。

图拓扑（线性 DAG，review 节点支持条件回跳）:

    information_collection
        └→ analysis
            └→ feature_analysis
                └→ pricing_analysis
                    └→ sentiment_analysis
                        └→ positioning_analysis
                            └→ role_analysis
                                └→ gtm_analysis
                                    └→ report_writing
                                        └→ review

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
REROUTE_TARGETS = (
    "information_collection",
    "analysis",
    "feature_analysis",
    "pricing_analysis",
    "sentiment_analysis",
    "positioning_analysis",
    "role_analysis",
    "gtm_analysis",
    "report_writing",
)

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
    """分析编排阶段制品工厂 —— 当前只持久化未拆出的 swot artifact。"""
    config = data.get("config", {}) if isinstance(data.get("config"), dict) else {}
    target = config.get("target_product", "")
    artifacts: list[ArtifactDraft] = []
    content = patch.get("swot")
    if content is not None:
        artifacts.append(
            ArtifactDraft(
                artifact_type="swot_analysis",
                title=f"{target} swot_analysis",
                content=content,
                created_by_node="analysis",
            )
        )
    return artifacts


def _single_analysis_artifact(node_id: str, artifact_type: str, key: str):
    def _factory(patch: dict, data: dict) -> list[ArtifactDraft]:
        content = patch.get(key)
        if content is None:
            return []
        config = data.get("config", {}) if isinstance(data.get("config"), dict) else {}
        target = config.get("target_product", "")
        return [
            ArtifactDraft(
                artifact_type=artifact_type,
                title=f"{target} {artifact_type}",
                content=content,
                created_by_node=node_id,
            )
        ]

    return _factory


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
        "positioning_analysis": None,
        "swot": None,
        "gtm_analysis": None,
        "analysis_modules": {},
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
            default_next="feature_analysis",
            allowed_routes=REROUTE_TARGETS,
            retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
            route_policy=DefaultRoutePolicy(),
            artifact_factory=_analysis_artifacts,
        ),
        NodeSpec(
            id="feature_analysis",
            agent=_analysis_agent,
            default_next="pricing_analysis",
            allowed_routes=REROUTE_TARGETS,
            retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
            route_policy=DefaultRoutePolicy(),
            artifact_factory=_single_analysis_artifact("feature_analysis", "feature_matrix", "feature_matrix"),
        ),
        NodeSpec(
            id="pricing_analysis",
            agent=_analysis_agent,
            default_next="sentiment_analysis",
            allowed_routes=REROUTE_TARGETS,
            retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
            route_policy=DefaultRoutePolicy(),
            artifact_factory=_single_analysis_artifact("pricing_analysis", "pricing_comparison", "pricing_comparison"),
        ),
        NodeSpec(
            id="sentiment_analysis",
            agent=_analysis_agent,
            default_next="positioning_analysis",
            allowed_routes=REROUTE_TARGETS,
            retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
            route_policy=DefaultRoutePolicy(),
            artifact_factory=_single_analysis_artifact("sentiment_analysis", "user_sentiment", "user_sentiment"),
        ),
        NodeSpec(
            id="positioning_analysis",
            agent=_analysis_agent,
            default_next="role_analysis",
            allowed_routes=REROUTE_TARGETS,
            retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
            route_policy=DefaultRoutePolicy(),
            artifact_factory=_single_analysis_artifact("positioning_analysis", "positioning_analysis", "positioning_analysis"),
        ),
        NodeSpec(
            id="role_analysis",
            agent=_analysis_agent,
            default_next="gtm_analysis",
            allowed_routes=REROUTE_TARGETS,
            retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
            route_policy=DefaultRoutePolicy(),
            artifact_factory=_single_analysis_artifact("role_analysis", "competitor_role_analysis", "competitor_role_analysis"),
        ),
        NodeSpec(
            id="gtm_analysis",
            agent=_analysis_agent,
            default_next="report_writing",
            allowed_routes=REROUTE_TARGETS,
            retry_policy=RetryPolicy(max_attempts=3, timeout_sec=300),
            route_policy=DefaultRoutePolicy(),
            artifact_factory=_single_analysis_artifact("gtm_analysis", "gtm_analysis", "gtm_analysis"),
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
