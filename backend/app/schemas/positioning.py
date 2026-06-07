from pydantic import BaseModel, Field

from app.schemas.evidence import EvidenceRef


class PositioningDimension(BaseModel):
    summary: str = ""
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class PositioningAnalysis(BaseModel):
    target_users: PositioningDimension = Field(default_factory=PositioningDimension)
    scenarios: PositioningDimension = Field(default_factory=PositioningDimension)
    problems: PositioningDimension = Field(default_factory=PositioningDimension)
    solutions: PositioningDimension = Field(default_factory=PositioningDimension)
    rtb: PositioningDimension = Field(default_factory=PositioningDimension)
    summary: str = ""
