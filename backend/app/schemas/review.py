from typing import Optional
from pydantic import BaseModel, Field


class ReviewCheck(BaseModel):
    dimension: str
    passed: bool
    detail: str


class ReviewOutput(BaseModel):
    passed: bool
    score: float
    checks: list[ReviewCheck]
    feedback: str
    target_node: Optional[str] = None
    specific_issues: list[str]
    primary_issue_type: Optional[str] = None
    issue_types: list[str] = Field(default_factory=list)
    affected_entities: list[str] = Field(default_factory=list)
    affected_artifacts: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    retry_worthiness: str = "unknown"
    retry_scope: Optional[str] = None
