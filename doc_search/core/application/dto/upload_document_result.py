"""DTO for document upload results."""

from dataclasses import dataclass


@dataclass
class UploadDocumentResult:
    """Result of an upload request."""

    job_id: str
    filename: str
    collection_name: str
    ingestion_mode: str
    status: str = "processing"
    error: str | None = None
