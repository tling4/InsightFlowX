import uuid

from app.core.competitive_template import CompetitiveAnalysisTemplate
from app.core.runtime.policies import ReviewFailPausePolicy, ReviewRoutePolicy
from app.core.runtime.template import GraphTemplate


def _review_result(passed: bool, target_node: str | None = "analysis") -> dict:
    return {
        "passed": passed,
        "score": 45,
        "checks": [],
        "feedback": "needs work",
        "target_node": target_node,
        "specific_issues": ["issue"],
    }


def test_competitive_template_declares_business_nodes_and_gate_nodes():
    template = CompetitiveAnalysisTemplate

    assert isinstance(template, GraphTemplate)
    assert template.entrypoint == "information_collection"
    assert template.node_ids == (
        "information_collection",
        "analysis",
        "feature_analysis",
        "pricing_analysis",
        "sentiment_analysis",
        "positioning_analysis",
        "role_analysis",
        "gtm_analysis",
        "report_writing",
        "review",
    )
    assert template.node("review").gate_id == "review__gate"


def test_pause_request_is_ui_metadata_not_full_dag_state():
    spec = CompetitiveAnalysisTemplate.node("review")
    run_id = uuid.uuid4()
    pause = ReviewFailPausePolicy().build_pause(
        {
            "data": {
                "review_result": _review_result(False),
                "raw_data": {"large": ["should not be copied"]},
            },
            "control": {"revision_count": 0, "max_revisions": 3},
            "runtime": {"run_id": str(run_id), "thread_id": "thread-1"},
        },
        spec,
    )

    assert pause is not None
    payload = pause.to_interrupt_payload({"runtime": {"run_id": str(run_id), "thread_id": "thread-1"}})
    assert payload["run_id"] == str(run_id)
    assert payload["thread_id"] == "thread-1"
    assert "dag_state" not in payload
    assert "raw_data" not in payload


def test_review_route_policy_prefers_human_jump_over_agent_target():
    spec = CompetitiveAnalysisTemplate.node("review")
    decision = ReviewRoutePolicy().decide(
        {
            "data": {"review_result": _review_result(False, target_node="analysis")},
            "control": {
                "revision_count": 0,
                "max_revisions": 3,
                "human_decision": {"action": "jump", "target_node": "information_collection"},
            },
            "runtime": {},
        },
        spec,
    )

    assert decision.action == "route"
    assert decision.next_node == "information_collection"


def test_review_route_policy_fails_at_max_revisions():
    spec = CompetitiveAnalysisTemplate.node("review")
    decision = ReviewRoutePolicy().decide(
        {
            "data": {"review_result": _review_result(False, target_node="analysis")},
            "control": {"revision_count": 3, "max_revisions": 3},
            "runtime": {},
        },
        spec,
    )

    assert decision.action == "fail"
