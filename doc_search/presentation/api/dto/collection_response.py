from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CollectionResponse(BaseModel):
    """Response model for collection."""

    collection_id: str
    name: str
    logo_url: Optional[str] = None
    created_at: str
    document_count: int
    # Optional summarized library card for the collection (not per-document)
    library_card_summary: Optional[str] = None
