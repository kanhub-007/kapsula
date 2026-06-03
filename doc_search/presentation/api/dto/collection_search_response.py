from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel
from doc_search.presentation.api.dto.citation import Citation
from doc_search.presentation.api.dto.search_result import SearchResult


class CollectionSearchResponse(BaseModel):
    """Response model for collection-level search."""

    query: str
    account_id: Optional[str] = None
    collection_id: Optional[str] = None
    total_results: int
    results: List[SearchResult]
    context_mode: Optional[str] = None
    citations: Optional[List[Citation]] = (
        None  # All unique citations from search results
    )
