import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Float, Boolean, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.db.base import Base


class TraceLink(Base):
    __tablename__ = "trace_link"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    artifact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("artifact.id", ondelete="CASCADE"), nullable=False)
    section_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claim_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="web")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
