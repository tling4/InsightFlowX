from pydantic import BaseModel, Field, field_validator


class SearchQuerySpec(BaseModel):
    intent: str = Field(..., min_length=1, description="Stable intent identifier")
    dimension: str = Field(default="", description="Focus dimension covered by this query")
    query_template: str = Field(..., min_length=1, description="Search query containing {product}")
    recovery_query_templates: list[str] = Field(default_factory=list, description="Alternative queries containing {product}")
    preferred_source_types: list[str] = Field(default_factory=list, description="Expected source types")

    @field_validator("query_template")
    @classmethod
    def query_template_requires_product(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if "{product}" not in normalized:
            raise ValueError("query_template must contain {product}")
        return normalized

    @field_validator("recovery_query_templates")
    @classmethod
    def recovery_templates_require_product(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values[:2]:
            query = " ".join(str(value).split())
            if query and "{product}" in query and query not in normalized:
                normalized.append(query)
        return normalized


class SearchQueryPlan(BaseModel):
    strategy_summary: str = ""
    queries: list[SearchQuerySpec] = Field(default_factory=list)
