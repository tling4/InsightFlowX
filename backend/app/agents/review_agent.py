import time

from app.agents.base_agent import BaseAgent
from app.agents.agent_utils import llm_is_configured
from app.agents.competitor_resolver import is_valid_competitor_name
from app.core.runtime.policies import ReviewFailPausePolicy
from app.core.runtime.context import AgentContext
from app.schemas.event import EventType
from app.schemas.review import ReviewCheck, ReviewOutput


REVIEW_SYSTEM_PROMPT = """你是竞品分析报告质检员。请审查输入报告和中间产物是否足以交付给用户。
要求：
- 只输出一个合法 JSON 对象，不要 Markdown，不要解释。
- score 为 0-100。
- passed 只有在 score >= 70 且没有关键问题时才为 true。
- 如果不通过，target_node 必须是 information_collection、analysis、report_writing 三者之一。
- 如果来源明显不足，target_node=information_collection；如果结构化 artifact 缺失，target_node=analysis；如果只有报告表达/组织问题，target_node=report_writing。
- 优先审查结构化 artifact，而不是只审查 Markdown 篇幅。
- 需要指出具体哪个 artifact 缺字段、缺 evidence、或覆盖了错误的竞品。
- 如果不通过，请补充失败分类：
  - primary_issue_type 只能是 transient_failure、structural_coverage_gap、artifact_inconsistency、report_render_issue 之一。
  - issue_types 为本次失败涉及到的分类列表。
  - affected_entities 列出受影响的产品、竞品或 artifact 名称。
  - affected_artifacts 列出具体 artifact 名称，例如 feature_matrix、pricing_comparison、positioning_analysis。
  - suggested_actions 只能从 retry_collection、rerun_analysis、rerender_report、review_competitor_scope、inspect_collection_config 中选择。
  - retry_worthiness 只能是 high、medium、low、none 之一。
  - retry_scope 用于标记优先重做的分析模块，例如 pricing_analysis、role_analysis。
- competitors 必须是明确产品/品牌/服务实体，不能是品类词、用户自然语言片段、媒体站、文章标题或泛化描述。
- 每个有效竞品都应有对应来源覆盖；有效竞品不足时必须不通过并回退 information_collection。
JSON schema:
{
  "passed": true,
  "score": 85,
  "checks": [{"dimension": "artifact_completeness", "passed": true, "detail": "..."}],
  "feedback": "...",
  "target_node": null,
  "specific_issues": ["..."],
  "primary_issue_type": null,
  "issue_types": [],
  "affected_entities": [],
  "affected_artifacts": [],
  "suggested_actions": [],
  "retry_worthiness": "unknown",
  "retry_scope": null
}"""


class ReviewAgent(BaseAgent):
    node_name = "review"

    async def run(self, state: dict, ctx: AgentContext) -> dict:
        await self.log_and_broadcast(ctx, EventType.NODE_START, {
            "input_summary": {"phase": "reviewing"},
        })
        await self.emit_progress(
            ctx,
            stage="check_source_coverage",
            message="正在检查目标产品与竞品的来源覆盖情况。",
        )
        await self.emit_progress(
            ctx,
            stage="check_structure",
            message="正在检查 artifact 完整性、evidence 绑定和报告一致性。",
        )

        start = time.time()

        if llm_is_configured():
            await self.emit_progress(
                ctx,
                stage="review_decision",
                message="正在综合来源、artifact 与报告内容给出审查结论。",
            )
            review = await self.invoke_llm(
                REVIEW_SYSTEM_PROMPT,
                {
                    "config": state.get("config"),
                    "raw_data_summary": {
                        product: len(items)
                        for product, items in (state.get("raw_data") or {}).items()
                    },
                    "artifact_summary": self._artifact_review_summary(state),
                    "feature_matrix": state.get("feature_matrix"),
                    "pricing_comparison": state.get("pricing_comparison"),
                    "user_sentiment": state.get("user_sentiment"),
                    "positioning_analysis": state.get("positioning_analysis"),
                    "swot": state.get("swot"),
                    "competitor_role_analysis": state.get("competitor_role_analysis"),
                    "gtm_analysis": state.get("gtm_analysis"),
                    "report": state.get("report"),
                    "competitor_quality": self._competitor_quality_summary(state),
                },
                ReviewOutput,
                ctx, "report_review",
            )
            review = self._apply_hard_gates(review, state)
            review = self._enrich_review_output(review, state)
            await self.log_and_broadcast(ctx, EventType.LLM_RESPONSE, {
                "model_task": "report_review",
                "score": review.score,
                "passed": review.passed,
            })
        else:
            await self.emit_progress(
                ctx,
                stage="rule_based_review",
                message="未使用实时模型审查，当前将按 artifact-first 规则检查报告质量与来源完整性。",
                level="warning",
            )
            review = self._rule_based_review(state)

        duration_ms = int((time.time() - start) * 1000)

        review_event = EventType.REVIEW_PASS if review.passed else EventType.REVIEW_FAIL
        await self.log_and_broadcast(ctx, review_event, {
            "score": review.score,
            "checks": [c.model_dump(mode="json") for c in review.checks],
            "feedback": review.feedback,
            "target_node": review.target_node,
            "specific_issues": review.specific_issues,
            "primary_issue_type": review.primary_issue_type,
            "issue_types": review.issue_types,
            "affected_entities": review.affected_entities,
            "affected_artifacts": review.affected_artifacts,
            "suggested_actions": review.suggested_actions,
            "retry_worthiness": review.retry_worthiness,
            "retry_scope": review.retry_scope,
        })
        if review.passed:
            await self.emit_progress(
                ctx,
                stage="review_passed",
                message=f"审查通过，当前评分 {review.score}，报告可以进入完成态。",
                level="success",
            )
        else:
            reroute_target = review.target_node or "analysis"
            await self.emit_progress(
                ctx,
                stage="review_failed",
                message=f"当前结果未通过审查，建议回退到 {reroute_target} 节点。原因：{review.feedback or '需要继续修订'}",
                level="warning",
            )

        await self.log_and_broadcast(ctx, EventType.NODE_COMPLETE, {
            "output_summary": {"passed": review.passed, "score": review.score},
            "duration_ms": duration_ms,
        })

        if not review.passed:
            revision_count = state.get("revision_count", 0)
            max_revisions = state.get("max_revisions", 3)
            if revision_count >= max_revisions:
                await self.emit_progress(
                    ctx,
                    stage="review_max_revisions",
                    message=f"已达到最大修订次数 {max_revisions}，本轮将停止继续回退。",
                    level="warning",
                )
                await self.log_and_broadcast(ctx, EventType.REVIEW_FAILED_MAX_REVISIONS, {
                    "revision_count": revision_count,
                    "max_revisions": max_revisions,
                    "score": review.score,
                })
                return {
                    "review_result": review.model_dump(mode="json"),
                    "current_phase": "reviewing",
                }
            await self.emit_progress(
                ctx,
                stage="await_human_decision",
                message=ReviewFailPausePolicy._build_pause_reason(review.model_dump(mode="json")),
                level="warning",
            )

        return {
            "review_result": review.model_dump(mode="json"),
            "current_phase": "reviewing",
        }

    def _rule_based_review(self, state: dict) -> ReviewOutput:
        report = state.get("report") or {}
        config = state.get("config") or {}
        if not isinstance(config, dict):
            config = {}
        raw_data = state.get("raw_data") or {}
        feature_matrix = state.get("feature_matrix") or {}
        pricing = state.get("pricing_comparison") or {}
        sentiment = state.get("user_sentiment") or {}
        positioning = state.get("positioning_analysis") or {}
        swot = state.get("swot") or {}
        gtm_analysis = state.get("gtm_analysis") or {}

        markdown = report.get("full_markdown", "") if isinstance(report, dict) else ""
        citations = report.get("citations", []) if isinstance(report, dict) else []
        source_count = sum(len(items) for items in raw_data.values()) if isinstance(raw_data, dict) else 0
        competitor_quality = self._competitor_quality_summary(state)
        artifact_summary = self._artifact_review_summary(state)
        traceability_ok = self._has_minimum_traceability(feature_matrix, pricing, positioning, gtm_analysis)

        checks = [
            ReviewCheck(
                dimension="completeness",
                passed=len(markdown) >= 500 and len(report.get("sections", [])) >= 4,
                detail="报告包含足够正文和章节" if len(markdown) >= 500 else "报告正文过短或章节不足",
            ),
            ReviewCheck(
                dimension="evidence",
                passed=source_count > 0 and len(citations) > 0,
                detail="报告包含采集来源和引用" if source_count > 0 and citations else "缺少真实采集来源或引用",
            ),
            ReviewCheck(
                dimension="artifact_completeness",
                passed=artifact_summary["complete"],
                detail="结构化 artifact 完整" if artifact_summary["complete"] else "结构化 artifact 不完整：" + "、".join(artifact_summary["missing_artifacts"]),
            ),
            ReviewCheck(
                dimension="consistency",
                passed=bool(report.get("title")) and bool(report.get("executive_summary")),
                detail="标题和摘要存在" if report.get("title") and report.get("executive_summary") else "缺少标题或摘要",
            ),
            ReviewCheck(
                dimension="competitor_validity",
                passed=competitor_quality["valid"],
                detail=competitor_quality["validity_detail"],
            ),
            ReviewCheck(
                dimension="source_coverage",
                passed=competitor_quality["source_coverage_ok"],
                detail=competitor_quality["coverage_detail"],
            ),
            ReviewCheck(
                dimension="artifact_traceability",
                passed=traceability_ok,
                detail="关键 artifact 已绑定最小证据" if traceability_ok else "关键 artifact 仍缺少 evidence 绑定",
            ),
        ]

        passed_count = sum(1 for check in checks if check.passed)
        score = round(passed_count / len(checks) * 100, 1)
        evidence_ok = checks[1].passed
        competitor_ok = competitor_quality["valid"] and competitor_quality["source_coverage_ok"]
        passed = score >= 70 and evidence_ok and competitor_ok
        target_node = None
        if not passed:
            collection_errors = state.get("collection_errors") or {}
            if (
                source_count == 0
                or not competitor_ok
                or "__competitor_resolution__" in collection_errors
                or "__source_coverage__" in collection_errors
            ):
                target_node = "information_collection"
            elif not artifact_summary["complete"]:
                target_node = "analysis"
            else:
                target_node = "report_writing"

        issues = [check.detail for check in checks if not check.passed]
        review = ReviewOutput(
            passed=passed,
            score=score,
            checks=checks,
            feedback="审查通过" if passed else "；".join(issues),
            target_node=target_node,
            specific_issues=issues,
        )
        return self._enrich_review_output(review, state)

    def _apply_hard_gates(self, review: ReviewOutput, state: dict) -> ReviewOutput:
        competitor_quality = self._competitor_quality_summary(state)
        if competitor_quality["valid"] and competitor_quality["source_coverage_ok"]:
            return review

        checks = list(review.checks)
        existing_dimensions = {check.dimension for check in checks}
        if "competitor_validity" not in existing_dimensions:
            checks.append(ReviewCheck(
                dimension="competitor_validity",
                passed=competitor_quality["valid"],
                detail=competitor_quality["validity_detail"],
            ))
        if "source_coverage" not in existing_dimensions:
            checks.append(ReviewCheck(
                dimension="source_coverage",
                passed=competitor_quality["source_coverage_ok"],
                detail=competitor_quality["coverage_detail"],
            ))

        issues = list(review.specific_issues)
        for detail in (competitor_quality["validity_detail"], competitor_quality["coverage_detail"]):
            if detail and detail not in issues:
                issues.append(detail)

        hard_gate_feedback = "竞品实体或来源覆盖未通过硬性校验"
        feedback = review.feedback
        if hard_gate_feedback not in feedback:
            feedback = f"{feedback}；{hard_gate_feedback}" if feedback else hard_gate_feedback

        review = ReviewOutput(
            passed=False,
            score=min(review.score, 60),
            checks=checks,
            feedback=feedback,
            target_node="information_collection",
            specific_issues=issues,
        )
        return self._enrich_review_output(review, state)

    def _enrich_review_output(self, review: ReviewOutput, state: dict) -> ReviewOutput:
        payload = review.model_dump(mode="json")
        if review.passed:
            payload.update({
                "primary_issue_type": None,
                "issue_types": [],
                "affected_entities": [],
                "affected_artifacts": [],
                "suggested_actions": [],
                "retry_worthiness": "none",
                "retry_scope": None,
            })
            return ReviewOutput.model_validate(payload)

        classification = self._classify_failure(review, state)
        payload.update(classification)
        if payload.get("target_node") == "analysis" and payload.get("retry_scope"):
            payload["target_node"] = payload["retry_scope"]
        return ReviewOutput.model_validate(payload)

    def _classify_failure(self, review: ReviewOutput, state: dict) -> dict:
        competitor_quality = self._competitor_quality_summary(state)
        collection_errors = state.get("collection_errors") or {}
        artifact_summary = self._artifact_review_summary(state)

        issue_types: list[str] = []
        affected_entities: list[str] = []
        affected_artifacts: list[str] = []
        suggested_actions: list[str] = []

        transient_error_messages = [
            str(msg)
            for key, msg in collection_errors.items()
            if not key.startswith("__") and self._looks_transient_collection_error(msg)
        ]
        if transient_error_messages:
            issue_types.append("transient_failure")
            suggested_actions.append("retry_collection")

        structural_coverage_gap = (
            review.target_node == "information_collection"
            or bool(competitor_quality["invalid_competitors"])
            or bool(competitor_quality["missing_source_products"])
            or "__competitor_resolution__" in collection_errors
            or "__source_coverage__" in collection_errors
        )
        if structural_coverage_gap:
            issue_types.append("structural_coverage_gap")
            suggested_actions.extend(["review_competitor_scope", "inspect_collection_config"])
            affected_entities.extend(
                item["name"]
                for item in competitor_quality["invalid_competitors"]
                if item.get("name")
            )
            affected_entities.extend(competitor_quality["missing_source_products"])

        analysis_gaps = [
            check.dimension
            for check in review.checks
            if not check.passed and check.dimension == "artifact_completeness"
        ]
        if review.target_node == "analysis" or analysis_gaps:
            issue_types.append("artifact_inconsistency")
            suggested_actions.append("rerun_analysis")
            affected_artifacts.extend(artifact_summary["missing_artifacts"] or self._infer_affected_artifacts(review))
            affected_entities.extend(affected_artifacts or ["feature_matrix", "pricing_comparison"])

        report_gaps = [
            check.dimension
            for check in review.checks
            if not check.passed and check.dimension in {"completeness", "consistency"}
        ]
        if review.target_node == "report_writing" or report_gaps:
            issue_types.append("report_render_issue")
            suggested_actions.append("rerender_report")
            affected_entities.extend(["report"])

        if not issue_types:
            if review.target_node == "analysis":
                issue_types.append("artifact_inconsistency")
                suggested_actions.append("rerun_analysis")
            elif review.target_node == "report_writing":
                issue_types.append("report_render_issue")
                suggested_actions.append("rerender_report")
            else:
                issue_types.append("structural_coverage_gap")
                suggested_actions.append("review_competitor_scope")

        primary_issue_type = issue_types[0]
        retry_worthiness = self._infer_retry_worthiness(issue_types, suggested_actions)
        return {
            "primary_issue_type": primary_issue_type,
            "issue_types": self._dedupe_preserve_order(issue_types),
            "affected_entities": self._dedupe_preserve_order(affected_entities),
            "affected_artifacts": self._dedupe_preserve_order(affected_artifacts),
            "suggested_actions": self._dedupe_preserve_order(suggested_actions),
            "retry_worthiness": retry_worthiness,
            "retry_scope": self._infer_retry_scope(affected_artifacts),
        }

    def _artifact_review_summary(self, state: dict) -> dict:
        required = {
            "feature_matrix": bool((state.get("feature_matrix") or {}).get("matrix")),
            "pricing_comparison": bool((state.get("pricing_comparison") or {}).get("plans")),
            "user_sentiment": bool((state.get("user_sentiment") or {}).get("per_product")),
        }
        missing = [name for name, complete in required.items() if not complete]
        if not ((state.get("positioning_analysis") or {}).get("summary") or (state.get("swot") or {}).get("strengths")):
            missing.append("positioning_analysis")
        return {
            "complete": not missing,
            "required_artifacts": list(required.keys()) + ["positioning_analysis"],
            "missing_artifacts": missing,
        }

    def _has_minimum_traceability(self, feature_matrix: dict, pricing: dict, positioning: dict, gtm_analysis: dict) -> bool:
        feature_rows = feature_matrix.get("matrix", []) if isinstance(feature_matrix, dict) else []
        if feature_rows:
            first_row = feature_rows[0]
            comparisons = first_row.get("comparisons", []) if isinstance(first_row, dict) else []
            if comparisons and isinstance(comparisons[0], dict) and comparisons[0].get("evidence_refs"):
                return True
        plans = pricing.get("plans", []) if isinstance(pricing, dict) else []
        if plans:
            tiers = plans[0].get("tiers", []) if isinstance(plans[0], dict) else []
            if tiers and isinstance(tiers[0], dict) and tiers[0].get("evidence_refs"):
                return True
        if isinstance(positioning, dict):
            for key in ("target_users", "scenarios", "problems", "solutions", "rtb"):
                value = positioning.get(key)
                if isinstance(value, dict) and value.get("evidence_refs"):
                    return True
        if isinstance(gtm_analysis, dict):
            for key in ("launch_rhythm", "channel_mix", "content_strategy"):
                value = gtm_analysis.get(key)
                if isinstance(value, dict) and value.get("evidence_refs"):
                    return True
        return False

    def _infer_affected_artifacts(self, review: ReviewOutput) -> list[str]:
        detail = "；".join(review.specific_issues)
        mapping = {
            "feature_matrix": ["feature_matrix", "功能"],
            "pricing_comparison": ["pricing_comparison", "定价"],
            "user_sentiment": ["user_sentiment", "反馈"],
            "positioning_analysis": ["positioning_analysis", "定位"],
            "competitor_role_analysis": ["competitor_role_analysis", "角色"],
            "gtm_analysis": ["gtm_analysis", "增长", "上市"],
        }
        matched: list[str] = []
        for artifact, hints in mapping.items():
            if any(hint in detail for hint in hints):
                matched.append(artifact)
        return self._dedupe_preserve_order(matched)

    def _infer_retry_scope(self, affected_artifacts: list[str]) -> str | None:
        mapping = {
            "feature_matrix": "feature_analysis",
            "pricing_comparison": "pricing_analysis",
            "user_sentiment": "sentiment_analysis",
            "positioning_analysis": "positioning_analysis",
            "competitor_role_analysis": "role_analysis",
            "gtm_analysis": "gtm_analysis",
        }
        for artifact in affected_artifacts:
            if artifact in mapping:
                return mapping[artifact]
        return None

    def _infer_retry_worthiness(self, issue_types: list[str], suggested_actions: list[str]) -> str:
        if not issue_types:
            return "unknown"
        if issue_types == ["transient_failure"]:
            return "high"
        if "transient_failure" in issue_types:
            return "medium"
        if "structural_coverage_gap" in issue_types and "retry_collection" not in suggested_actions:
            return "low"
        if "report_render_issue" in issue_types and len(issue_types) == 1:
            return "high"
        if "artifact_inconsistency" in issue_types:
            return "medium"
        return "low"

    @staticmethod
    def _looks_transient_collection_error(message: str | None) -> bool:
        if not message:
            return False
        normalized = str(message).lower()
        keywords = (
            "timeout",
            "timed out",
            "temporarily",
            "temporary",
            "connection reset",
            "connection error",
            "network",
            "429",
            "rate limit",
            "too many requests",
            "service unavailable",
            "gateway timeout",
        )
        return any(keyword in normalized for keyword in keywords)

    @staticmethod
    def _dedupe_preserve_order(items: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            if not item or item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    def _competitor_quality_summary(self, state: dict) -> dict:
        config = state.get("config") or {}
        raw_data = state.get("raw_data") or {}
        collection_errors = state.get("collection_errors") or {}
        if not isinstance(config, dict):
            config = {}
        if not isinstance(raw_data, dict):
            raw_data = {}

        target = config.get("target_product", "")
        category = config.get("product_category", "")
        product_profile = config.get("product_profile")
        competitors = config.get("competitors", []) or []
        insufficient_evidence = {
            name.lower()
            for name in (config.get("insufficient_evidence_competitors") or [])
            if isinstance(name, str)
        }
        requested_count = int(config.get("competitor_count") or len(competitors) or 0)

        if not target and not competitors:
            return {
                "valid": True,
                "source_coverage_ok": True,
                "validity_detail": "未提供工作流配置，跳过竞品有效性检查",
                "coverage_detail": "未提供工作流配置，跳过竞品来源覆盖检查",
                "invalid_competitors": [],
                "missing_source_products": [],
            }
        if target and "competitors" not in config and "competitor_count" not in config:
            return {
                "valid": True,
                "source_coverage_ok": True,
                "validity_detail": "配置未包含竞品字段，跳过竞品有效性检查",
                "coverage_detail": "配置未包含竞品字段，跳过竞品来源覆盖检查",
                "invalid_competitors": [],
                "missing_source_products": [],
            }

        invalid = []
        for competitor in competitors:
            ok, reason = is_valid_competitor_name(competitor, target, category, product_profile)
            if not ok:
                invalid.append({"name": competitor, "reason": reason})

        minimum_competitors = 1 if requested_count <= 1 else min(2, requested_count)
        valid_count = len(competitors) - len(invalid)
        resolution_error = collection_errors.get("__competitor_resolution__")
        coverage_error = collection_errors.get("__source_coverage__")
        has_resolution_error = bool(resolution_error)
        valid = valid_count >= minimum_competitors and not invalid and not has_resolution_error

        products_to_check = [product for product in [target, *competitors] if product]
        missing_sources = [
            product for product in products_to_check
            if not isinstance(raw_data.get(product), list) or len(raw_data.get(product, [])) == 0
        ]
        blocking_missing_sources = [
            product for product in missing_sources
            if product == target or product.lower() not in insufficient_evidence
        ]
        source_coverage_ok = not blocking_missing_sources

        if invalid:
            validity_detail = "存在无效竞品：" + "，".join(f"{item['name']}({item['reason']})" for item in invalid)
        elif has_resolution_error:
            validity_detail = resolution_error
        elif valid_count < minimum_competitors:
            validity_detail = f"有效竞品数量不足：{valid_count}/{minimum_competitors}"
        else:
            validity_detail = "竞品均为明确产品实体"

        if blocking_missing_sources:
            coverage_detail = "以下产品缺少来源：" + "，".join(blocking_missing_sources)
            if coverage_error:
                coverage_detail = f"{coverage_error}；{coverage_detail}"
        elif missing_sources:
            coverage_detail = "以下竞品证据不足但已允许继续：" + "，".join(missing_sources)
        else:
            coverage_detail = "目标产品与竞品均有来源覆盖"

        return {
            "valid": valid,
            "source_coverage_ok": source_coverage_ok,
            "validity_detail": validity_detail,
            "coverage_detail": coverage_detail,
            "invalid_competitors": invalid,
            "missing_source_products": blocking_missing_sources,
        }
