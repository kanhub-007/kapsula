"""In-memory progress tracker backed by the shared processing_status store."""

from kapsula.core.domain.interfaces.progress_tracker import ProgressTracker
from kapsula.infrastructure.repositories.data.sql_upload_job_repository import (
    SqlUploadJobRepository,
)
from kapsula.infrastructure.repositories.processing.upload_progress_store import (
    processing_status,
)


class InMemoryProgressTracker(ProgressTracker):
    """Uses the shared ``processing_status`` store plus a persistent job row."""

    def __init__(self, job_repository: SqlUploadJobRepository | None = None):
        self._jobs = job_repository or SqlUploadJobRepository()

    def register_job(
        self,
        job_id: str,
        filename: str,
        collection_name: str,
        ingestion_mode: str,
    ) -> None:
        processing_status[job_id] = {
            "status": "processing",
            "progress": 0,
            "stage": "queued",
            "message": f"Document queued for {ingestion_mode} ingestion...",
            "ingestion_mode": ingestion_mode,
        }
        self._jobs.create(
            job_id,
            filename=filename,
            collection_name=collection_name,
            collection_id=None,  # set by caller if needed
            ingestion_mode=ingestion_mode,
        )

    def set_queued(self, job_id: str, ingestion_mode: str) -> None:
        processing_status[job_id] = {
            "status": "processing",
            "progress": 0,
            "stage": "queued",
            "message": f"Document queued for {ingestion_mode} ingestion...",
            "ingestion_mode": ingestion_mode,
        }
