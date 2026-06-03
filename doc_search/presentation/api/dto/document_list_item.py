from __future__ import annotations

from typing import Optional

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
    duration: Optional[float]
    chunk_count: int
