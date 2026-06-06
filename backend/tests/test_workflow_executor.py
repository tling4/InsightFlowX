import uuid
from types import SimpleNamespace

import pytest

from app.core.pause_service import extract_interrupt_payload, make_pause_state
from app.core.workflow_executor import _get_or_create_run


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


@pytest.mark.asyncio
async def test_get_or_create_run_flushes_run_before_assigning_foreign_key():
    workflow = SimpleNamespace(
        id=uuid.uuid4(),
        current_run_id=None,
        execution_attempt=1,
        langgraph_checkpoint_id=None,
    )

    class RecordingSession:
        def __init__(self):
            self.calls = []
            self.run = None

        def add(self, run):
            self.run = run
            self.calls.append(("add", workflow.current_run_id))

        async def flush(self, objects):
            assert objects == [self.run]
            self.calls.append(("flush", workflow.current_run_id))

        async def commit(self):
            self.calls.append(("commit", workflow.current_run_id))

        async def refresh(self, run):
            self.calls.append(("refresh", workflow.current_run_id))

    db = RecordingSession()
    run = await _get_or_create_run(db, workflow)

    assert db.calls[0:2] == [("add", None), ("flush", None)]
    assert workflow.current_run_id == run.id
    assert db.calls[2][0] == "commit"
