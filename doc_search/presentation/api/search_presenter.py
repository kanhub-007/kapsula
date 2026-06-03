"""Presentation helpers for API search responses."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from doc_search.presentation.api.models import (
    Citation,
    CollectionSearchResponse,
    SearchResult,
)

CitationExtractor = Callable[[dict, Session, int | None], Citation | None]


def collect_unique_citations(citations: list[Citation | None]) -> list[Citation]:
    """Remove duplicate citations based on library_card_id and char positions."""
    seen = set()
    unique = []
    for citation in citations:
        if citation is None:
            continue
        key = (citation.library_card_id, citation.start_char, citation.end_char)
        if key not in seen:
            seen.add(key)
            unique.append(citation)
    return unique


def to_search_result(result: dict[str, Any], citation: Citation | None) -> SearchResult:
    """Map an application search-result dict to the API model."""
    return SearchResult(
        index=result["index"],
        content=result.get("expanded_content", result["content"]),
        score=result.get("score", 0.0),
        dense_score=result.get("dense_score", 0.0),
        sparse_score=result.get("sparse_score", 0.0),
        rerank_score=result.get("rerank_score"),
        sub_document_key=result.get("sub_document_key"),
        contributing_chunks=result.get("contributing_chunks"),
        parent_hash=result.get("parent_hash"),
        collection_name=result.get("collection_name"),
        document_filename=result.get("document_filename"),
        retrieval_score=result.get("retrieval_score"),
        collection_route_confidence=result.get("collection_route_confidence"),
        subdocument_route_confidence=result.get("subdocument_route_confidence"),
        metadata_route_confidence=result.get("metadata_route_confidence"),
        citation=citation,
    )


def build_collection_search_response(
    *,
    query: str,
    account_id: str | None,
    collection_id: str | None,
    results: list[dict[str, Any]],
    context_mode: str,
    db: Session,
    extract_citation: CitationExtractor,
) -> CollectionSearchResponse:
    """Build a collection search API response from application results."""
    search_results = []
    citations = []
    for result in results:
        citation = extract_citation(result, db, result.get("document_id"))
        search_results.append(to_search_result(result, citation))
        citations.append(citation)

    return CollectionSearchResponse(
        query=query,
        account_id=account_id,
        collection_id=collection_id,
        total_results=len(search_results),
        results=search_results,
        context_mode=context_mode,
        citations=collect_unique_citations(citations),
    )
