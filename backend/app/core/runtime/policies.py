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

from app.schemas.workflow import WorkflowConfig, assign_competitor_groups, remove_competitors_from_groups
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
        issue_type = review.get("primary_issue_type")
        suggested_actions = review.get("suggested_actions", []) or []
        retry_scope = review.get("retry_scope")
        retry_label = self._build_retry_label(issue_type, target, suggested_actions, retry_scope)
        reason = self._build_pause_reason(review)
        options = [
            {"value": "jump", "label": retry_label, "target_node": target},
            {"value": "approve", "label": "强制通过（接受当前报告）"},
            {"value": "abort", "label": "放弃本次分析"},
        ]
        if issue_type == "structural_coverage_gap":
            options = [
                {"value": "drop_competitor", "label": "移除缺失竞品并继续", "target_node": "information_collection"},
                {"value": "keep_with_insufficient_evidence", "label": "保留竞品但标记证据不足", "target_node": "report_writing"},
                {
                    "value": "replace_competitor",
                    "label": "替换缺失竞品（使用输入框）",
                    "target_node": "information_collection",
                    "requires_input": True,
                },
                *options,
            ]
        return PauseRequest(
            node_id=spec.id,
            reason=reason,
            suggested_route=target,
            options=options,
            context={
                "score": review.get("score"),
                "checks": review.get("checks", []),
                "specific_issues": review.get("specific_issues", []),
                "primary_issue_type": review.get("primary_issue_type"),
                "issue_types": review.get("issue_types", []),
                "affected_entities": review.get("affected_entities", []),
                "affected_artifacts": review.get("affected_artifacts", []),
                "suggested_actions": review.get("suggested_actions", []),
                "retry_worthiness": review.get("retry_worthiness", "unknown"),
                "retry_scope": retry_scope,
                "target_node": target,
            },
        )

    def apply_decision(self, state: dict, spec: NodeSpec, decision: dict) -> dict:
        action = decision.get("action")
        if action not in {
            "drop_competitor",
            "keep_with_insufficient_evidence",
            "replace_competitor",
        }:
            return {"data": state.get("data") or {}, "control": state.get("control") or {}, "decision": decision}

        data = dict(state.get("data") or {})
        control = dict(state.get("control") or {})
        config = data.get("config") or {}
        if not isinstance(config, dict):
            return {"data": data, "control": control, "decision": decision}

        workflow_config = WorkflowConfig(**config)
        affected = self._resolve_affected_competitors(data, decision)
        if not affected:
            return {"data": data, "control": control, "decision": decision}

        if action == "drop_competitor":
            workflow_config = self._drop_competitors(workflow_config, affected)
            data = self._cleanup_after_competitor_change(data, affected)
            decision = {
                **decision,
                "target_node": decision.get("target_node") or "information_collection",
                "feedback": decision.get("feedback") or f"移除竞品：{', '.join(affected)}",
            }
        elif action == "keep_with_insufficient_evidence":
            existing = workflow_config.insufficient_evidence_competitors
            workflow_config.insufficient_evidence_competitors = list(dict.fromkeys(existing + affected))
            note = f"以下竞品证据不足但需保留分析，并在报告中明确标注：{', '.join(affected)}。"
            if note not in workflow_config.extra_requirements:
                workflow_config.extra_requirements = f"{workflow_config.extra_requirements}\n{note}".strip()
            decision = {
                **decision,
                "target_node": decision.get("target_node") or "report_writing",
                "feedback": decision.get("feedback") or f"保留证据不足竞品：{', '.join(affected)}",
            }
        elif action == "replace_competitor":
            replacement = (decision.get("replacement_competitor") or "").strip()
            if not replacement:
                return {"data": data, "control": control, "decision": decision}
            workflow_config = self._drop_competitors(workflow_config, affected)
            workflow_config.competitors = list(dict.fromkeys(workflow_config.competitors + [replacement]))
            workflow_config.competitor_groups = assign_competitor_groups(
                workflow_config.competitors,
                workflow_config.competitor_groups,
            )
            data = self._cleanup_after_competitor_change(data, affected + [replacement])
            decision = {
                **decision,
                "target_node": decision.get("target_node") or "information_collection",
                "feedback": decision.get("feedback") or f"替换竞品 {', '.join(affected)} -> {replacement}",
            }

        data["config"] = workflow_config.model_dump(mode="json")
        control["human_decision"] = decision
        return {"data": data, "control": control, "decision": decision}

    @staticmethod
    def _build_pause_reason(review: dict) -> str:
        score = review.get("score", 0)
        base_reason = review.get("feedback") or f"报告评分 {score}，未通过质检"
        issue_type = review.get("primary_issue_type")
        retry_worthiness = review.get("retry_worthiness", "unknown")
        issue_labels = {
            "transient_failure": "临时失败",
            "structural_coverage_gap": "结构性缺源",
            "artifact_inconsistency": "分析产物问题",
            "report_render_issue": "报告表达问题",
        }
        retry_labels = {
            "high": "建议直接重试",
            "medium": "可尝试定向重试",
            "low": "不建议盲目重试",
            "none": "无需重试",
            "unknown": "需人工判断",
        }
        if not issue_type:
            return base_reason
        return f"{base_reason}（失败类型：{issue_labels.get(issue_type, issue_type)}；{retry_labels.get(retry_worthiness, retry_worthiness)}）"

    @staticmethod
    def _build_retry_label(issue_type: str | None, target: str, suggested_actions: list[str], retry_scope: str | None = None) -> str:
        if issue_type == "transient_failure":
            return "重试采集（临时失败）"
        if issue_type == "structural_coverage_gap":
            if "review_competitor_scope" in suggested_actions:
                return "重新采集并检查竞品范围"
            return "重新采集来源"
        scope_labels = {
            "feature_analysis": "重新生成功能矩阵",
            "pricing_analysis": "重新生成定价分析",
            "sentiment_analysis": "重新生成用户反馈分析",
            "positioning_analysis": "重新生成定位分析",
            "role_analysis": "重新生成竞品角色判断",
            "gtm_analysis": "重新生成上市与增长分析",
        }
        if retry_scope in scope_labels:
            return scope_labels[retry_scope]
        if issue_type == "artifact_inconsistency" or target == "analysis":
            return "重新生成分析结果"
        if issue_type == "report_render_issue" or target == "report_writing":
            return "重新组织报告"
        return "按建议重试"

    @staticmethod
    def _resolve_affected_competitors(data: dict, decision: dict) -> list[str]:
        config = data.get("config") or {}
        competitors = config.get("competitors", []) if isinstance(config, dict) else []
        competitor_set = {item.lower(): item for item in competitors if isinstance(item, str)}
        explicit = (decision.get("competitor") or "").strip()
        if explicit:
            matched = competitor_set.get(explicit.lower())
            if matched:
                return [matched]
        review = data.get("review_result") or {}
        affected = review.get("affected_entities", []) if isinstance(review, dict) else []
        resolved: list[str] = []
        for entity in affected:
            if not isinstance(entity, str):
                continue
            matched = competitor_set.get(entity.lower())
            if matched:
                resolved.append(matched)
        return list(dict.fromkeys(resolved))

    @staticmethod
    def _drop_competitors(config: WorkflowConfig, affected: list[str]) -> WorkflowConfig:
        lowered = {name.lower() for name in affected}
        config.competitors = [name for name in config.competitors if name.lower() not in lowered]
        config.insufficient_evidence_competitors = [
            name for name in config.insufficient_evidence_competitors if name.lower() not in lowered
        ]
        config.competitor_groups = remove_competitors_from_groups(config.competitor_groups, affected)
        return WorkflowConfig(**config.model_dump(mode="json"))

    @staticmethod
    def _cleanup_after_competitor_change(data: dict, affected: list[str]) -> dict:
        cleaned = dict(data)
        removals = {name.lower() for name in affected}
        raw_data = dict(cleaned.get("raw_data") or {})
        cleaned["raw_data"] = {
            key: value for key, value in raw_data.items()
            if not isinstance(key, str) or key.lower() not in removals
        }
        collection_errors = dict(cleaned.get("collection_errors") or {})
        cleaned["collection_errors"] = {
            key: value for key, value in collection_errors.items()
            if not isinstance(key, str) or (not key.startswith("__") and key.lower() not in removals)
        }
        cleaned["collection_errors"].pop("__source_coverage__", None)
        cleaned["collection_errors"].pop("__competitor_resolution__", None)
        cleaned["review_result"] = None
        return cleaned


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
        if human_decision.get("action") in {
            "jump",
            "drop_competitor",
            "keep_with_insufficient_evidence",
            "replace_competitor",
        }:
            target = human_decision.get("target_node")
        if target not in spec.allowed_routes:
            target = review.get("target_node")
        if target not in spec.allowed_routes:
            target = "analysis"
        return ControlDecision(action="route", next_node=target, reason="review failed reroute")
