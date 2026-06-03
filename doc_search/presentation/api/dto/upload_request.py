"""Upload request API DTO."""

from typing import Optional

from pydantic import BaseModel


class UploadRequest(BaseModel):
    """Request model for document upload."""

    collection_id: str
    max_tokens: Optional[int] = 512
    ingestion_mode: Optional[str] = "indexed"
