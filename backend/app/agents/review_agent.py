import time
import uuid
from app.agents.base_agent import BaseAgent
from app.agents.agent_utils import llm_is_configured
from app.agents.competitor_resolver import is_valid_competitor_name
from app.services.event_service import EventLogger
from app.schemas.event import EventType
from app.schemas.review import ReviewOutput, ReviewCheck


REVIEW_SYSTEM_PROMPT = """你是竞品分析报告质检员。请审查输入报告和中间产物是否足以交付给用户。
要求：
- 只输出一个合法 JSON 对象，不要 Markdown，不要解释。
- score 为 0-100。
- passed 只有在 score >= 70 且没有关键问题时才为 true。
- 如果不通过，target_node 必须是 information_collection、analysis、report_writing 三者之一。
- 如果来源明显不足，target_node=information_collection；如果分析结构缺失，target_node=analysis；如果只有报告表达/组织问题，target_node=report_writing。
- competitors 必须是明确产品/品牌/服务实体，不能是品类词、用户自然语言片段、媒体站、文章标题或泛化描述。
- 每个有效竞品都应有对应来源覆盖；有效竞品不足时必须不通过并回退 information_collection。
JSON schema:
{
  "passed": true,
  "score": 85,
  "checks": [{"dimension": "completeness", "passed": true, "detail": "..."}],
  "feedback": "...",
  "target_node": null,
  "specific_issues": ["..."]
}"""


class ReviewAgent(BaseAgent):
    """报告质检 Agent。

    审查维度：完整性、证据、分析结构、一致性。
    不通过时通过 target_node 指定回退目标节点，由 orchestrator 的条件路由决定
    是重做采集/分析/报告，还是超出重试上限后强制结束。
    """

    node_name = "review"

    async def run(self, state: dict, event_logger: EventLogger, workflow_id: uuid.UUID) -> dict:
        await self.log_and_broadcast(event_logger, EventType.NODE_START, {
            "input_summary": {"phase": "reviewing"},
        }, workflow_id)
        await self.emit_progress(
            event_logger,
            workflow_id,
            stage="check_source_coverage",
            message="正在检查目标产品与竞品的来源覆盖情况。",
        )
        await self.emit_progress(
            event_logger,
            workflow_id,
            stage="check_structure",
            message="正在检查分析结构、报告完整性与结论一致性。",
        )

        start = time.time()

        if llm_is_configured():
            await self.emit_progress(
                event_logger,
                workflow_id,
                stage="review_decision",
                message="正在综合来源、分析结果与报告内容给出审查结论。",
            )
            review = await self.invoke_llm(
                REVIEW_SYSTEM_PROMPT,
                {
                    "config": state.get("config"),
                    "raw_data_summary": {
                        product: len(items)
                        for product, items in (state.get("raw_data") or {}).items()
                    },
                    "feature_matrix": state.get("feature_matrix"),
                    "pricing_comparison": state.get("pricing_comparison"),
                    "user_sentiment": state.get("user_sentiment"),
                    "swot": state.get("swot"),
                    "report": state.get("report"),
                    "competitor_quality": self._competitor_quality_summary(state),
                },
                ReviewOutput,
                event_logger, workflow_id, "report_review",
            )
            review = self._apply_hard_gates(review, state)
            await self.log_and_broadcast(event_logger, EventType.LLM_RESPONSE, {
                "model_task": "report_review",
                "score": review.score,
                "passed": review.passed,
            }, workflow_id)
        else:
            await self.emit_progress(
                event_logger,
                workflow_id,
                stage="rule_based_review",
                message="未使用实时模型审查，当前将按规则检查报告质量与来源完整性。",
                level="warning",
            )
            review = self._rule_based_review(state)

        duration_ms = int((time.time() - start) * 1000)

        review_event = EventType.REVIEW_PASS if review.passed else EventType.REVIEW_FAIL
        await self.log_and_broadcast(event_logger, review_event, {
            "score": review.score,
            "checks": [c.model_dump(mode="json") for c in review.checks],
            "feedback": review.feedback,
            "target_node": review.target_node,
            "specific_issues": review.specific_issues,
        }, workflow_id)
        if review.passed:
            await self.emit_progress(
                event_logger,
                workflow_id,
                stage="review_passed",
                message=f"审查通过，当前评分 {review.score}，报告可以进入完成态。",
                level="success",
            )
        else:
            reroute_target = review.target_node or "analysis"
            await self.emit_progress(
                event_logger,
                workflow_id,
                stage="review_failed",
                message=f"当前结果未通过审查，建议回退到 {reroute_target} 节点。原因：{review.feedback or '需要继续修订'}",
                level="warning",
            )

        await self.log_and_broadcast(event_logger, EventType.NODE_COMPLETE, {
            "output_summary": {"passed": review.passed, "score": review.score},
            "duration_ms": duration_ms,
        }, workflow_id)

        if not review.passed:
            revision_count = state.get("revision_count", 0)
            max_revisions = state.get("max_revisions", 3)
            if revision_count >= max_revisions:
                await self.emit_progress(
                    event_logger,
                    workflow_id,
                    stage="review_max_revisions",
                    message=f"已达到最大修订次数 {max_revisions}，本轮将停止继续回退。",
                    level="warning",
                )
                await self.log_and_broadcast(event_logger, EventType.REVIEW_FAILED_MAX_REVISIONS, {
                    "revision_count": revision_count,
                    "max_revisions": max_revisions,
                    "score": review.score,
                }, workflow_id)
                return {
                    "review_result": review.model_dump(mode="json"),
                    "review_reroute_target": None,
                    "review_result_consumed": False,
                    "current_phase": "reviewing",
                }
            pause_reason = review.feedback or f"报告评分 {review.score}，未通过质检"
            await self.emit_progress(
                event_logger,
                workflow_id,
                stage="await_human_decision",
                message=pause_reason,
                level="warning",
            )
            return {
                "__pause__": True,
                "pause_reason": pause_reason,
                "pause_options": [
                    {"value": "jump", "label": "按建议重试", "target_node": review.target_node or "analysis"},
                    {"value": "approve", "label": "强制通过（接受当前报告）"},
                    {"value": "abort", "label": "放弃本次分析"},
                ],
                "pause_context": {
                    "score": review.score,
                    "checks": [c.model_dump(mode="json") for c in review.checks],
                    "specific_issues": review.specific_issues,
                    "target_node": review.target_node,
                },
                "review_result": review.model_dump(mode="json"),
                "review_reroute_target": None,
                "review_result_consumed": False,
                "current_phase": "reviewing",
            }

        return {
            "review_result": review.model_dump(mode="json"),
            "review_reroute_target": None,
            "review_result_consumed": False,
            "current_phase": "reviewing",
        }

    def _rule_based_review(self, state: dict) -> ReviewOutput:
        """无 LLM 时的规则审查：基于结构完整性做简单打分。

        四个检查项：
        - completeness:     报告正文 >= 500 字且 >= 4 个章节
        - evidence:         有搜索来源且有引用
        - analysis_structure: 四个分析产物均非空
        - consistency:      标题和摘要存在

        passed 需要 score >= 70 且 evidence 必须通过。
        回退优先级：来源不足 → 重采集；分析缺失 → 重分析；其余 → 重报告。
        """
        report = state.get("report") or {}
        config = state.get("config") or {}
        if not isinstance(config, dict):
            config = {}
        raw_data = state.get("raw_data") or {}
        feature_matrix = state.get("feature_matrix") or {}
        pricing = state.get("pricing_comparison") or {}
        sentiment = state.get("user_sentiment") or {}
        swot = state.get("swot") or {}

        markdown = report.get("full_markdown", "") if isinstance(report, dict) else ""
        citations = report.get("citations", []) if isinstance(report, dict) else []
        source_count = sum(len(items) for items in raw_data.values()) if isinstance(raw_data, dict) else 0
        competitor_quality = self._competitor_quality_summary(state)

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
                dimension="analysis_structure",
                passed=bool(feature_matrix.get("matrix")) and bool(pricing.get("plans")) and bool(sentiment.get("per_product")) and bool(swot.get("strengths")),
                detail="结构化分析产物完整" if feature_matrix.get("matrix") else "结构化分析产物不完整",
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
        ]

        passed_count = sum(1 for check in checks if check.passed)
        score = round(passed_count / len(checks) * 100, 1)
        # evidence/competitor validity/source coverage 是硬性要求。
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
            elif not checks[2].passed:
                target_node = "analysis"
            else:
                target_node = "report_writing"

        issues = [check.detail for check in checks if not check.passed]
        return ReviewOutput(
            passed=passed,
            score=score,
            checks=checks,
            feedback="审查通过" if passed else "；".join(issues),
            target_node=target_node,
            specific_issues=issues,
        )

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

        return ReviewOutput(
            passed=False,
            score=min(review.score, 60),
            checks=checks,
            feedback=feedback,
            target_node="information_collection",
            specific_issues=issues,
        )

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
        hard_collection_error = (
            collection_errors.get("__competitor_resolution__")
            or collection_errors.get("__source_coverage__")
        )
        has_collection_hard_error = bool(hard_collection_error)
        valid = valid_count >= minimum_competitors and not invalid and not has_collection_hard_error

        products_to_check = [product for product in [target, *competitors] if product]
        missing_sources = [
            product for product in products_to_check
            if not isinstance(raw_data.get(product), list) or len(raw_data.get(product, [])) == 0
        ]
        source_coverage_ok = not missing_sources and not has_collection_hard_error

        if invalid:
            validity_detail = "存在无效竞品：" + "，".join(f"{item['name']}({item['reason']})" for item in invalid)
        elif has_collection_hard_error:
            validity_detail = hard_collection_error
        elif valid_count < minimum_competitors:
            validity_detail = f"有效竞品数量不足：{valid_count}/{minimum_competitors}"
        else:
            validity_detail = "竞品均为明确产品实体"

        if missing_sources:
            coverage_detail = "以下产品缺少来源：" + "，".join(missing_sources)
        elif has_collection_hard_error:
            coverage_detail = hard_collection_error
        else:
            coverage_detail = "目标产品与竞品均有来源覆盖"

        return {
            "valid": valid,
            "source_coverage_ok": source_coverage_ok,
            "validity_detail": validity_detail,
            "coverage_detail": coverage_detail,
            "invalid_competitors": invalid,
            "missing_source_products": missing_sources,
        }
