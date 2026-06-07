from pydantic import BaseModel, Field

from app.schemas.evidence import EvidenceRef


class GTMSection(BaseModel):
    summary: str = ""
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class GTMAnalysis(BaseModel):
    launch_rhythm: GTMSection = Field(default_factory=GTMSection)
    budget_allocation: GTMSection = Field(default_factory=GTMSection)
    channel_mix: GTMSection = Field(default_factory=GTMSection)
    content_strategy: GTMSection = Field(default_factory=GTMSection)
    paid_acquisition: GTMSection = Field(default_factory=GTMSection)
    business_results: GTMSection = Field(default_factory=GTMSection)
    summary: str = ""
