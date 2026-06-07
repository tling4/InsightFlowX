from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class EvidenceRef(BaseModel):
    url: str = ""
    title: str = ""
    snippet: str = ""
    source_type: str = "web"
    confidence: float = Field(default=0.5, ge=0, le=1)
    captured_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_url_shorthand(cls, data: Any) -> Any:
        """Accept the common LLM shorthand of returning only the source URL."""
        if isinstance(data, str):
            return {"url": data, "title": data}
        return data
