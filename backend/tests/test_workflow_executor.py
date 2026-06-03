from app.core.pause_service import extract_interrupt_payload, make_pause_state


class DummyInterrupt:
    def __init__(self, value):
        self.value = value


def test_extract_interrupt_payload_from_langgraph_state():
    payload = {
        "paused_by_node": "review",
        "pause_reason": "needs collection",
        "pause_context": {"score": 35},
    }

    assert extract_interrupt_payload({"__interrupt__": [DummyInterrupt(payload)]}) == payload


def test_make_pause_state_keeps_dag_state_for_resume():
    pause_state = make_pause_state({
        "paused_by_node": "review",
        "pause_reason": "bad competitors",
        "pause_options": [{"value": "jump"}],
        "pause_context": {"target_node": "information_collection"},
        "dag_state": {"review_result": {"passed": False}},
    })

    assert pause_state["paused_by_node"] == "review"
    assert pause_state["dag_state"]["review_result"]["passed"] is False
    assert "paused_at" in pause_state
