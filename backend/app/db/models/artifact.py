import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import JSON
from sqlalchemy.sql import func
from app.db.base import Base


class Artifact(Base):
    """工作流产物：包含采集数据、分析矩阵、报告等各类输出。既存 JSON content 也存 content_text 以支持全文检索。"""

    __tablename__ = "artifact"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    format_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    created_by_node: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
