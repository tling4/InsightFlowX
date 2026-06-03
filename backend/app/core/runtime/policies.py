"""具体的路由策略和暂停策略实现。

所有策略都遵循 template.py 中定义的 RoutePolicy / PausePolicy 协议，
通过 NodeSpec 配置到图中。策略本身不感知执行细节，
只根据 state 做出路由或暂停决策。

现有关键策略：
    DefaultRoutePolicy     所有节点的默认前向路由（default_next）
    ReviewRoutePolicy      质检节点的条件路由（通过 → 完成 / 不通过 → 重试 / 耗尽 → 失败）
    ReviewFailPausePolicy  质检不通过时的人工审核暂停
"""

from __future__ import annotations

from app.core.runtime.template import ControlDecision, NodeSpec, PauseRequest


class DefaultRoutePolicy:
    """默认前向路由策略。

    所有未显式指定 route_policy 的节点使用此策略：
        - default_next == "done" → finish（终止）
        - 否则 → continue（沿 default_next 前向边继续）

    此策略从不触发 reroute（不产生 REROUTE 事件），
    只在 DAG 的天然拓扑上线性推进。
    """

    def decide(self, state: dict, spec: NodeSpec) -> ControlDecision:
        if spec.default_next == "done":
            return ControlDecision(action="finish", reason="default terminal route")
        return ControlDecision(action="continue", next_node=spec.default_next)


class ReviewFailPausePolicy:
    """质检不通过时的人工审核暂停策略。

    在 gate node 中先于 RoutePolicy 调用。
    检查条件：
        - data.review_result.passed is False
        - revision_count < max_revisions（还有重试空间）

    满足条件时构建 PauseRequest，包含三个操作选项：
        "jump"    按 agent 建议的目标节点重试
        "approve" 强制通过，接受当前报告
        "abort"   放弃本次分析

    前端通过 POST /workflows/{id}/decide 提交决策后，
    gate node 将 decision 存入 control["human_decision"]。
    """

    def build_pause(self, state: dict, spec: NodeSpec) -> PauseRequest | None:
        data = state.get("data") or {}
        control = state.get("control") or {}
        review = data.get("review_result")
        if not isinstance(review, dict) or review.get("passed") is not False:
            return None

        revision_count = int(control.get("revision_count", data.get("revision_count", 0)) or 0)
        max_revisions = int(control.get("max_revisions", data.get("max_revisions", 3)) or 3)
        if revision_count >= max_revisions:
            return None

        target = review.get("target_node") if review.get("target_node") in spec.allowed_routes else "analysis"
        reason = review.get("feedback") or f"报告评分 {review.get('score', 0)}，未通过质检"
        return PauseRequest(
            node_id=spec.id,
            reason=reason,
            suggested_route=target,
            options=[
                {"value": "jump", "label": "按建议重试", "target_node": target},
                {"value": "approve", "label": "强制通过（接受当前报告）"},
                {"value": "abort", "label": "放弃本次分析"},
            ],
            context={
                "score": review.get("score"),
                "checks": review.get("checks", []),
                "specific_issues": review.get("specific_issues", []),
                "target_node": target,
            },
        )


class ReviewRoutePolicy:
    """质检节点路由策略。

    根据 data.review_result 的内容决定图的走向：
        - passed is True              → finish（正常完成）
        - revision_count >= max       → fail（超限失败）
        - 有人工 jump 指令            → route 到指定目标
        - agent 指定了 target_node    → route 到目标（默认 "analysis"）

    注意：此策略假定 gate node 已经通过 PausePolicy + interrupt()
    等待了人工决策。人工决策（如果有）在 control["human_decision"] 中。
    """

    def decide(self, state: dict, spec: NodeSpec) -> ControlDecision:
        data = state.get("data") or {}
        control = state.get("control") or {}
        review = data.get("review_result")
        if not isinstance(review, dict):
            return ControlDecision(action="fail", reason="review node did not produce review_result")

        if review.get("passed") is True:
            return ControlDecision(action="finish", reason="review passed")

        revision_count = int(control.get("revision_count", data.get("revision_count", 0)) or 0)
        max_revisions = int(control.get("max_revisions", data.get("max_revisions", 3)) or 3)
        if revision_count >= max_revisions:
            return ControlDecision(action="fail", reason=review.get("feedback") or "review failed at max revisions")

        human_decision = control.get("human_decision") or {}
        target = None
        if human_decision.get("action") == "jump":
            target = human_decision.get("target_node")
        if target not in spec.allowed_routes:
            target = review.get("target_node")
        if target not in spec.allowed_routes:
            target = "analysis"
        return ControlDecision(action="route", next_node=target, reason="review failed reroute")
