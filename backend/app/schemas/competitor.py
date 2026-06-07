from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class CompetitorInfo(BaseModel):
    name: str
    website: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None


class SearchResult(BaseModel):
    url: str
    title: str
    snippet: str
    content_summary: Optional[str] = None
    source_query: Optional[str] = None
    source_intent: Optional[str] = None
    source_intents: list[str] = Field(default_factory=list)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
