from __future__ import annotations

from pydantic import BaseModel

from kapsula.presentation.api.dto.citation import Citation
from kapsula.presentation.api.dto.search_result import SearchResult


class CollectionSearchResponse(BaseModel):
    """Response model for collection-level search."""

    query: str
    account_id: str | None = None
    collection_id: str | None = None
    total_results: int
    results: list[SearchResult]
    context_mode: str | None = None
    citations: list[Citation] | None = None  # All unique citations from search results
