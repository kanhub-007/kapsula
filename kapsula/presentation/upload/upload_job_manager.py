"""Persistent upload job manager."""

from datetime import UTC, datetime

from kapsula.infrastructure.data import SessionLocal, UploadJob
from kapsula.infrastructure.logging_config import get_logger
from kapsula.presentation.upload.upload_progress_tracker import UploadProgressTracker

logger = get_logger(__name__)


class UploadJobManager:
    """Persistent upload job CRUD that optionally syncs with a live progress tracker."""

    def __init__(self, progress_tracker: UploadProgressTracker | None = None):
        self._progress = progress_tracker

    def create(
        self,
        job_id: str,
        *,
        filename: str,
        collection_id: int,
        collection_name: str,
        ingestion_mode: str,
    ) -> None:
        """Create a new upload job record and live progress entry."""
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

        if self._progress:
            self._progress.set(
                job_id,
                status="processing",
                progress=0,
                stage="queued",
                message=f"Document queued for {ingestion_mode} ingestion...",
                ingestion_mode=ingestion_mode,
            )

    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        stage: str | None = None,
        message: str | None = None,
        chunk_count: int | None = None,
        subdocument_count: int | None = None,
        duration: float | None = None,
        error: str | None = None,
        ingestion_mode: str | None = None,
    ) -> None:
        """Update both the DB record and live progress."""
        db = SessionLocal()
        try:
            job = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
            if not job:
                logger.warning("UploadJob %s not found for update", job_id)
                return

            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = progress
            if stage is not None:
                job.stage = stage
            if message is not None:
                job.message = message
            if chunk_count is not None:
                job.chunk_count = chunk_count
            if subdocument_count is not None:
                job.subdocument_count = subdocument_count
            if duration is not None:
                job.duration = duration
            if error is not None:
                job.error = error
            if ingestion_mode is not None:
                job.ingestion_mode = ingestion_mode

            job.updated_at = datetime.now(UTC)
            db.commit()
        finally:
            db.close()

    def get(self, job_id: str) -> dict | None:
        """Return a job as a dict from DB."""
        db = SessionLocal()
        try:
            job = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
            if not job:
                return None
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
        finally:
            db.close()

    def list_recent(self, limit: int = 50) -> list[dict]:
        """Return recent upload jobs ordered by creation time."""
        db = SessionLocal()
        try:
            jobs = (
                db.query(UploadJob)
                .order_by(UploadJob.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                {
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
                    "created_at": (
                        job.created_at.isoformat() if job.created_at else None
                    ),
                    "updated_at": (
                        job.updated_at.isoformat() if job.updated_at else None
                    ),
                }
                for job in jobs
            ]
        finally:
            db.close()
