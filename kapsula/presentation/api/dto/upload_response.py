"""Upload response API DTO."""

from pydantic import BaseModel


class UploadResponse(BaseModel):
    """Response model for document upload."""

    job_id: str
    collection_id: str
    status: str
    message: str
    ingestion_mode: str = "indexed"
