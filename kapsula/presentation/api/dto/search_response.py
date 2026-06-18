from __future__ import annotations

from pydantic import BaseModel

from kapsula.presentation.api.dto.citation import Citation
from kapsula.presentation.api.dto.search_result import SearchResult


class SearchResponse(BaseModel):
    """Response model for search."""

    job_id: str
    query: str
    total_results: int
    results: list[SearchResult]
    context_mode: str | None = None
    node_type_filter: list[str] | None = None
    citations: list[Citation] | None = None  # All unique citations from search results
