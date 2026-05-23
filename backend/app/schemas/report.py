from datetime import date, datetime
from pydantic import BaseModel, Field


class ReportSection(BaseModel):
    heading: str
    level: int
    content: str
    source_refs: list[str] = []


class Citation(BaseModel):
    index: int
    url: str
    title: str
    access_date: date


class ReportOutput(BaseModel):
    title: str
    executive_summary: str
    sections: list[ReportSection]
    citations: list[Citation]
    full_markdown: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
