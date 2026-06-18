from __future__ import annotations

from pydantic import BaseModel


class CollectionResponse(BaseModel):
    """Response model for collection."""

    collection_id: str
    name: str
    logo_url: str | None = None
    created_at: str
    document_count: int
    # Optional summarized library card for the collection (not per-document)
    library_card_summary: str | None = None
