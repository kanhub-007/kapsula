from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel
from kapsula.presentation.api.dto.citation import Citation


class SearchResult(BaseModel):
    """Single search result."""

    index: int
    content: str
    score: float
    dense_score: float
    sparse_score: float
    rerank_score: Optional[float] = None  # Shows reranker score if reranking enabled
    sub_document_key: Optional[str] = (
        None  # Shows which sub-document this result came from
    )
    contributing_chunks: Optional[List[int]] = (
        None  # Chunk indices that contributed to this result (for deduplicated parents)
    )
    parent_hash: Optional[str] = (
        None  # Parent section hash (when context expansion is used)
    )
    collection_name: Optional[str] = (
        None  # Collection name (for collection-level search)
    )
    document_filename: Optional[str] = (
        None  # Document filename (for collection-level search)
    )
    retrieval_score: Optional[float] = None  # Original score before route weighting
    collection_route_confidence: Optional[float] = None
    subdocument_route_confidence: Optional[float] = None
    metadata_route_confidence: Optional[float] = None
    citation: Optional[Citation] = None  # Citation information for tracing origin
