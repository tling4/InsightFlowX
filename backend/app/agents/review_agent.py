import time
import uuid
from app.agents.base_agent import BaseAgent
from app.agents.agent_utils import invoke_json_model, llm_is_configured
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
    node_name = "review"

    async def run(self, state: dict, event_logger: EventLogger, workflow_id: uuid.UUID) -> dict:
        """Review report quality and decide whether to reroute."""
        await self.log_and_broadcast(event_logger, EventType.NODE_START, {
            "input_summary": {"phase": "reviewing"},
        }, workflow_id)

        start = time.time()

        if llm_is_configured():
            await self.log_and_broadcast(event_logger, EventType.LLM_REQUEST, {
                "model_task": "report_review",
            }, workflow_id)
            review = await invoke_json_model(
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
                },
                ReviewOutput,
            )
            await self.log_and_broadcast(event_logger, EventType.LLM_RESPONSE, {
                "model_task": "report_review",
                "score": review.score,
                "passed": review.passed,
            }, workflow_id)
        else:
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

        if not review.passed and review.target_node:
            await self.log_and_broadcast(event_logger, EventType.REVIEW_REROUTE, {
                "target_node": review.target_node,
                "revision_count": state.get("revision_count", 0) + 1,
                "feedback": review.feedback,
            }, workflow_id)

        await self.log_and_broadcast(event_logger, EventType.NODE_COMPLETE, {
            "output_summary": {"passed": review.passed, "score": review.score},
            "duration_ms": duration_ms,
        }, workflow_id)

        return {
            "review_result": review.model_dump(mode="json"),
            "revision_count": state.get("revision_count", 0) + (0 if review.passed else 1),
            "current_phase": "reviewing",
        }

    def _rule_based_review(self, state: dict) -> ReviewOutput:
        report = state.get("report") or {}
        raw_data = state.get("raw_data") or {}
        feature_matrix = state.get("feature_matrix") or {}
        pricing = state.get("pricing_comparison") or {}
        sentiment = state.get("user_sentiment") or {}
        swot = state.get("swot") or {}

        markdown = report.get("full_markdown", "") if isinstance(report, dict) else ""
        citations = report.get("citations", []) if isinstance(report, dict) else []
        source_count = sum(len(items) for items in raw_data.values()) if isinstance(raw_data, dict) else 0

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
        ]

        passed_count = sum(1 for check in checks if check.passed)
        score = round(passed_count / len(checks) * 100, 1)
        evidence_ok = checks[1].passed
        passed = score >= 70 and evidence_ok
        target_node = None
        if not passed:
            if source_count == 0:
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
