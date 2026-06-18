"""Upload request API DTO."""

from pydantic import BaseModel


class UploadRequest(BaseModel):
    """Request model for document upload."""

    collection_id: str
    max_tokens: int | None = 512
    ingestion_mode: str | None = "indexed"
