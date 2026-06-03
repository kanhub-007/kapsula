"""Upload job tracking model."""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from ..connection import Base


class UploadJob(Base):
    """Persistent record of an upload job for progress tracking across restarts."""

    __tablename__ = "upload_jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, unique=True, nullable=False, index=True)
    filename = Column(String, nullable=False)
    collection_id = Column(Integer, nullable=True)
    collection_name = Column(String, nullable=True)
    status = Column(String, nullable=False, default="queued")
    progress = Column(Integer, nullable=False, default=0)
    stage = Column(String, nullable=True)
    message = Column(Text, nullable=True)
    ingestion_mode = Column(String, nullable=True)
    chunk_count = Column(Integer, nullable=True)
    subdocument_count = Column(Integer, nullable=True)
    duration = Column(Float, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
