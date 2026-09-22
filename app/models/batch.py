import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class BatchStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status: Mapped[str] = mapped_column(String(32), default=BatchStatus.QUEUED, nullable=False)
    variables: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    documents: Mapped[list["Document"]] = relationship(  # noqa: F821
        back_populates="batch", cascade="all, delete-orphan"
    )
