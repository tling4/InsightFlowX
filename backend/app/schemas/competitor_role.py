from pydantic import BaseModel, Field

from app.schemas.evidence import EvidenceRef


class CompetitorRoleItem(BaseModel):
    product: str
    role: str = Field(description="core / benchmark / potential / substitute / pitfall / unknown")
    reason: str
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class CompetitorRoleAnalysis(BaseModel):
    items: list[CompetitorRoleItem] = Field(default_factory=list)
    summary: str = ""
