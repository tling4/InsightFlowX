from pydantic import BaseModel, Field

from app.schemas.evidence import EvidenceRef


class PricingTier(BaseModel):
    name: str
    price: float = 0
    raw_price: str = ""
    currency: str = ""
    billing_period: str = ""
    pricing_model: str = ""
    highlights: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class PricingPlan(BaseModel):
    product: str
    tiers: list[PricingTier] = Field(default_factory=list)


class PricingComparison(BaseModel):
    plans: list[PricingPlan] = Field(default_factory=list)
    summary: str
