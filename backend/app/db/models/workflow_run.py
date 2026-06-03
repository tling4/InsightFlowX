import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class WorkflowRun(Base):
    """One executable attempt of a workflow.

    A workflow is the business aggregate; a run is the runtime execution unit
    tied to one LangGraph checkpoint thread.
    """

    __tablename__ = "workflow_run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow.id", ondelete="CASCADE"),
        nullable=False,
    )
    execution_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    thread_id: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    entrypoint: Mapped[str] = mapped_column(String(64), nullable=False, default="information_collection")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
