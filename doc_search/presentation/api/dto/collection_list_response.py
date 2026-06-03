from __future__ import annotations

from typing import List

from pydantic import BaseModel
from doc_search.presentation.api.dto.collection_response import CollectionResponse


class CollectionListResponse(BaseModel):
    """Response model for collection list."""

    collections: List[CollectionResponse]
    total: int
