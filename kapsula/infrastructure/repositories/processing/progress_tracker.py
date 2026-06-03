"""In-memory progress tracker backed by processing_status dict."""

from kapsula.core.domain.interfaces.progress_tracker import ProgressTracker
from kapsula.presentation.upload.upload_job_manager import UploadJobManager


class InMemoryProgressTracker(ProgressTracker):
    """Uses the module-level ``processing_status`` dict from tasks.py."""

    def register_job(
        self,
        job_id: str,
        filename: str,
        collection_name: str,
        ingestion_mode: str,
    ) -> None:
        from kapsula.presentation.api.tasks import processing_status

        processing_status[job_id] = {
            "status": "processing",
            "progress": 0,
            "stage": "queued",
            "message": f"Document queued for {ingestion_mode} ingestion...",
            "ingestion_mode": ingestion_mode,
        }
        UploadJobManager().create(
            job_id,
            filename=filename,
            collection_name=collection_name,
            collection_id=None,  # set by caller if needed
            ingestion_mode=ingestion_mode,
        )

    def set_queued(self, job_id: str, ingestion_mode: str) -> None:
        from kapsula.presentation.api.tasks import processing_status

        processing_status[job_id] = {
            "status": "processing",
            "progress": 0,
            "stage": "queued",
            "message": f"Document queued for {ingestion_mode} ingestion...",
            "ingestion_mode": ingestion_mode,
        }
