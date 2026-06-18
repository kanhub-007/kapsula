"""SQLAlchemy-backed UploadJobRepository.

Moved from presentation/upload/ to infrastructure/repositories/data/ to satisfy
the CQRS-lite rule (writes must live behind a repository) and the layer rule
(infrastructure must not import presentation). The previous ``UploadJobManager``
name is retained as a deprecated alias for callers that have not migrated.
"""

from datetime import UTC, datetime
from typing import Any

from kapsula.core.domain.interfaces.upload_job_repository import (
    UploadJobRepository,
)
from kapsula.infrastructure.data import SessionLocal, UploadJob
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class SqlUploadJobRepository(UploadJobRepository):
    """CRUD for UploadJob rows."""

    def create(
        self,
        job_id: str,
        *,
        filename: str,
        collection_id: int | None,
        collection_name: str,
        ingestion_mode: str,
    ) -> None:
        """Insert a new upload-job row in 'processing' state."""
        db = SessionLocal()
        try:
            job = UploadJob(
                job_id=job_id,
                filename=filename,
                collection_id=collection_id,
                collection_name=collection_name,
                status="processing",
                progress=0,
                stage="queued",
                message=f"Document queued for {ingestion_mode} ingestion...",
                ingestion_mode=ingestion_mode,
            )
            db.add(job)
            db.commit()
        finally:
            db.close()

    def update(self, job_id: str, **fields: Any) -> None:
        """Patch zero or more columns on an existing upload-job row."""
        db = SessionLocal()
        try:
            job = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
            if not job:
                logger.warning("UploadJob %s not found for update", job_id)
                return
            for key, value in fields.items():
                if value is not None and hasattr(job, key):
                    setattr(job, key, value)
            job.updated_at = datetime.now(UTC)
            db.commit()
        finally:
            db.close()

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Return one job as a plain dict, or None if not found."""
        db = SessionLocal()
        try:
            job = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
            if not job:
                return None
            return _job_to_dict(job)
        finally:
            db.close()

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent upload jobs ordered by creation time (newest first)."""
        db = SessionLocal()
        try:
            jobs = (
                db.query(UploadJob)
                .order_by(UploadJob.created_at.desc())
                .limit(limit)
                .all()
            )
            return [_job_to_dict(job) for job in jobs]
        finally:
            db.close()


def _job_to_dict(job: UploadJob) -> dict[str, Any]:
    """Serialize an UploadJob ORM instance to a plain dict."""
    return {
        "job_id": job.job_id,
        "filename": job.filename,
        "collection_name": job.collection_name,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "message": job.message,
        "ingestion_mode": job.ingestion_mode,
        "chunk_count": job.chunk_count,
        "subdocument_count": job.subdocument_count,
        "duration": job.duration,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


# Deprecated alias: kept so external callers (and MCP tools) importing
# ``UploadJobManager`` continue to work while they migrate to the repository
# name. New code should use ``SqlUploadJobRepository``.
UploadJobManager = SqlUploadJobRepository
