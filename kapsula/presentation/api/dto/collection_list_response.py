from __future__ import annotations

from pydantic import BaseModel

from kapsula.presentation.api.dto.collection_response import CollectionResponse


class CollectionListResponse(BaseModel):
    """Response model for collection list."""

    collections: list[CollectionResponse]
    total: int
