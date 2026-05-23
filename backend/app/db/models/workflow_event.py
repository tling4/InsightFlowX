import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import JSON
from sqlalchemy.sql import func
from app.db.base import Base


class WorkflowEvent(Base):
    __tablename__ = "workflow_event"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False)
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
