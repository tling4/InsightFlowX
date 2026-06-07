from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class EventType(str, Enum):
    NODE_START = "node_start"
    NODE_PROGRESS = "node_progress"
    NODE_COMPLETE = "node_complete"
    NODE_ERROR = "node_error"
    REVIEW_PASS = "review_pass"
    REVIEW_FAIL = "review_fail"
    REROUTE = "reroute"
    REVIEW_FAILED_MAX_REVISIONS = "review_failed_max_revisions"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    LLM_REQUEST = "llm_request"
    LLM_STREAM = "llm_stream"
    LLM_RESPONSE = "llm_response"
    WORKFLOW_START = "workflow_start"
    WORKFLOW_COMPLETE = "workflow_complete"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_PAUSED = "workflow_paused"
    WORKFLOW_RESUMED = "workflow_resumed"
    CONTEXT_COMPRESSED = "context_compressed"


class EventPayload(BaseModel):
    pass


class NodeStartPayload(EventPayload):
    input_summary: dict = Field(default_factory=dict)
    node_config: dict = Field(default_factory=dict)


class NodeProgressPayload(EventPayload):
    stage: str = ""
    message: str = ""
    level: str = "info"


class NodeCompletePayload(EventPayload):
    output_summary: dict = Field(default_factory=dict)
    artifact_ids: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    model_name: str = ""


class NodeErrorPayload(EventPayload):
    error_code: str = ""
    error_message: str = ""
    retry_count: int = 0
    max_retries: int = 3


class ReviewPayload(EventPayload):
    score: float = 0
    checks: list[dict] = Field(default_factory=list)
    feedback: str = ""
    target_node: Optional[str] = None
    specific_issues: list[str] = Field(default_factory=list)
    primary_issue_type: Optional[str] = None
    issue_types: list[str] = Field(default_factory=list)
    affected_entities: list[str] = Field(default_factory=list)
    affected_artifacts: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    retry_worthiness: str = "unknown"
    retry_scope: Optional[str] = None


class WorkflowEventResponse(BaseModel):
    id: str
    workflow_id: str
    node_name: str
    iteration: int
    event_type: str
    seq: int
    payload: dict
    created_at: datetime

    model_config = {"from_attributes": True}
