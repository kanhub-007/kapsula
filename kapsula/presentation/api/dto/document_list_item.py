from __future__ import annotations

from pydantic import BaseModel


class DocumentListItem(BaseModel):
    """Document list item."""

    id: int
    job_id: str
    collection_id: str
    collection_name: str
    filename: str
    size: int
    status: str
    created_at: str
    duration: float | None
    chunk_count: int
