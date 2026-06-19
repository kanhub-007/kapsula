"""Presentation helpers for API search responses."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from kapsula.core.application.dto.search_result_hit import SearchResultHit
from kapsula.presentation.api.models import (
    Citation,
    CollectionSearchResponse,
    SearchResult,
)

CitationExtractor = Callable[[SearchResultHit, Session, int | None], Citation | None]


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


def to_search_result(
    result: SearchResultHit, citation: Citation | None
) -> SearchResult:
    """Map a typed search-result hit to the API model."""
    expanded = result.expanded_content
    return SearchResult(
        index=result.index,
        content=expanded if expanded is not None else result.content,
        score=result.score,
        dense_score=result.dense_score,
        sparse_score=result.sparse_score,
        rerank_score=result.rerank_score,
        sub_document_key=result.sub_document_key,
        contributing_chunks=result.contributing_chunks,
        parent_hash=result.parent_hash,
        collection_name=result.collection_name,
        document_filename=result.document_filename,
        retrieval_score=result.retrieval_score,
        collection_route_confidence=result.collection_route_confidence,
        subdocument_route_confidence=result.subdocument_route_confidence,
        metadata_route_confidence=result.metadata_route_confidence,
        citation=citation,
    )


def build_collection_search_response(
    *,
    query: str,
    account_id: str | None,
    collection_id: str | None,
    results: list[SearchResultHit],
    context_mode: str,
    db: Session,
    extract_citation: CitationExtractor,
) -> CollectionSearchResponse:
    """Build a collection search API response from typed hits."""
    search_results = []
    citations = []
    for result in results:
        citation = extract_citation(result, db, result.document_id)
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


def collect_intelligent_citations(
    intelligent_result: dict,
    db: Session,
    extract_citation: CitationExtractor,
    document_id: int | None = None,
) -> list[Citation]:
    """Collect unique citations from an intelligent-search result dict.

    Closes H7: the relevant-results -> citations mapping (with its fallback
    to all results in multi-query planning mode) was copy-pasted across the
    document and collection intelligent-search routes.

    ``relevant_results`` are 0-based indices into ``search_results``. When the
    engine emits none (planning mode), every result is cited.
    """
    search_results: list[SearchResultHit] = intelligent_result.get("search_results", [])
    if not search_results:
        return []

    relevant_indices = intelligent_result.get("relevant_results", [])
    if not relevant_indices:
        chosen = search_results
    else:
        chosen = [
            search_results[i] for i in relevant_indices if 0 <= i < len(search_results)
        ]

    citations = [extract_citation(result, db, document_id) for result in chosen]
    return collect_unique_citations(citations)
