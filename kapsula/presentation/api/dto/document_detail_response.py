from __future__ import annotations

from pydantic import BaseModel


class DocumentDetailResponse(BaseModel):
    """Response model for document details."""

    id: int
    job_id: str
    collection_id: str
    collection_name: str
    filename: str
    size: int
    status: str
    created_at: str
    duration: float | None
    ip_address: str
    chunk_count: int
    structure: str | None  # Markdown skeleton structure
