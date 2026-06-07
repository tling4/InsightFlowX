from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.evidence import EvidenceRef


class FeatureComparison(BaseModel):
    product: str
    support_level: str = "unknown"
    difference_summary: str = ""
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_evidence_refs(cls, data: Any) -> Any:
        """Accept the common LLM shorthand of returning evidence URLs as strings."""
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        refs = normalized.get("evidence_refs")
        if isinstance(refs, list):
            normalized["evidence_refs"] = [
                {"url": ref, "title": ref}
                if isinstance(ref, str)
                else ref
                for ref in refs
            ]
        return normalized


class FeatureItem(BaseModel):
    module: str = "核心能力"
    feature_name: str
    comparisons: list[FeatureComparison] = Field(default_factory=list)
    products: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_feature_name(cls, data: Any) -> Any:
        """Map semantic aliases frequently used by LLMs to the schema field name."""
        if not isinstance(data, dict) or data.get("feature_name"):
            return data
        normalized = dict(data)
        for alias in ("dimension", "feature", "name"):
            if normalized.get(alias):
                normalized["feature_name"] = normalized[alias]
                break
        return normalized

    @model_validator(mode="after")
    def sync_legacy_products(self) -> "FeatureItem":
        if self.comparisons and not self.products:
            self.products = {
                item.product: item.difference_summary or item.support_level
                for item in self.comparisons
            }
        elif self.products and not self.comparisons:
            self.comparisons = [
                FeatureComparison(
                    product=product,
                    support_level="unknown",
                    difference_summary=summary,
                )
                for product, summary in self.products.items()
            ]
        return self


class FeatureMatrix(BaseModel):
    dimensions: list[str]
    matrix: list[FeatureItem]
