from __future__ import annotations

from pydantic import BaseModel

from kapsula.presentation.api.dto.citation import Citation


class SearchResult(BaseModel):
    """Single search result."""

    index: int
    content: str
    score: float
    dense_score: float
    sparse_score: float
    rerank_score: float | None = None  # Shows reranker score if reranking enabled
    sub_document_key: str | None = (
        None  # Shows which sub-document this result came from
    )
    contributing_chunks: list[int] | None = (
        None  # Chunk indices that contributed to this result (for deduplicated parents)
    )
    parent_hash: str | None = (
        None  # Parent section hash (when context expansion is used)
    )
    collection_name: str | None = None  # Collection name (for collection-level search)
    document_filename: str | None = (
        None  # Document filename (for collection-level search)
    )
    retrieval_score: float | None = None  # Original score before route weighting
    collection_route_confidence: float | None = None
    subdocument_route_confidence: float | None = None
    metadata_route_confidence: float | None = None
    citation: Citation | None = None  # Citation information for tracing origin
