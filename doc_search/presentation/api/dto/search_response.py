from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel
from doc_search.presentation.api.dto.citation import Citation
from doc_search.presentation.api.dto.search_result import SearchResult


class SearchResponse(BaseModel):
    """Response model for search."""

    job_id: str
    query: str
    total_results: int
    results: List[SearchResult]
    context_mode: Optional[str] = None
    node_type_filter: Optional[List[str]] = None
    citations: Optional[List[Citation]] = (
        None  # All unique citations from search results
    )
