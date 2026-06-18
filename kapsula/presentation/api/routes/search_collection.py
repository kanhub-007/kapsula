"""Search routes."""

import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from kapsula.core.application.dto.collection_search import CollectionSearch
from kapsula.core.application.dto.single_index_search import SingleIndexSearch
from kapsula.core.application.dto.sub_document_search import SubDocumentSearch
from kapsula.core.domain.text_processing import parse_node_type_filter
from kapsula.infrastructure.data.connection import get_db
from kapsula.infrastructure.data.tables.collection import Collection
from kapsula.infrastructure.data.tables.document import Document
from kapsula.infrastructure.data.tables.library_card import LibraryCard
from kapsula.infrastructure.data.tables.sub_document import SubDocument
from kapsula.infrastructure.logging_config import get_logger
from kapsula.presentation.api.search_presenter import (
    build_collection_search_response,
    collect_unique_citations,
)
from kapsula.startup import (
    create_multi_index_searcher,
    create_query_planner,
    create_intelligent_searcher,
    create_chat_client,
)
from ..models import (
    SearchResponse,
    SearchResult,
    CollectionSearchResponse,
    IntelligentSearchResponse,
    IntelligentCollectionSearchResponse,
    SearchPlan,
    SubAnswer,
    Citation,
)
from .search_helpers import extract_citation_from_result

logger = get_logger(__name__)
router = APIRouter()

@router.post("/collections", response_model=CollectionSearchResponse)
@router.post("/search/collections", response_model=CollectionSearchResponse)
async def search_across_collections(
    query: str = Query(..., description="Search query"),
    account_id: Optional[str] = Query(
        None, description="Account ID to search within (optional)"
    ),
    top_k: int = Query(10, ge=1, le=100, description="Number of results to return"),
    context_mode: str = Query(
        "none", description="Context expansion mode: none, narrow (H3), deep (H2)"
    ),
    node_type_filter: Optional[str] = Query(
        None, description="Comma-separated node types to filter (e.g., 'code,table')"
    ),
    routing_mode: str = Query("auto", description="Routing mode: auto, llm, or fast"),
    db: Session = Depends(get_db),
):
    """
    Search across multiple collections using LLM routing.

    Use this for broad exploration when you don't know which collection holds
    the answer. For targeted searches, use /search/collections/{collection_id}
    instead — it's faster and more precise.

    For LLM consumption, set context_mode="deep" to get full H2 chapter context.

    - **query**: Search query text
    - **account_id**: Optional account ID to filter collections
    - **top_k**: Number of results to return (1-100, default 10)
    - **context_mode**: "none" (raw chunk), "narrow" (H3 section), "deep" (H2 chapter)

    Returns search results with scores, content, and source information.
    """
    logger.info(
        f"Collection search request: '{query[:50]}...' (account_id={account_id})"
    )

    try:
        searcher = create_multi_index_searcher(db)
        results = await searcher.search_collections(
            CollectionSearch(
                query=query,
                account_id=account_id,
                top_k=top_k,
                context_mode=context_mode,
                hf_api_token=os.getenv("HF_TOKEN"),
                node_type_filter=parse_node_type_filter(node_type_filter),
                routing_mode=routing_mode,
            )
        )

        logger.info(
            f"Collection search completed: {len(results)} results (context={context_mode})"
        )
        return build_collection_search_response(
            query=query,
            account_id=account_id,
            collection_id=None,
            results=results,
            context_mode=context_mode,
            db=db,
            extract_citation=extract_citation_from_result,
        )

    except Exception as e:
        logger.error(f"Collection search failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Collection search failed: {str(e)}"
        )


@router.post("/collections/{collection_id}", response_model=CollectionSearchResponse)
async def search_collection(
    collection_id: str,
    query: str = Query(..., description="Search query"),
    top_k: int = Query(10, ge=1, le=100, description="Number of results to return"),
    context_mode: str = Query(
        "none", description="Context expansion mode: none, narrow (H3), deep (H2)"
    ),
    node_type_filter: Optional[str] = Query(
        None, description="Comma-separated node types to filter (e.g., 'code,table')"
    ),
    routing_mode: str = Query("auto", description="Routing mode: auto, llm, or fast"),
    db: Session = Depends(get_db),
):
    """
    Search within a single collection by collection_id.

    Faster and more precise than global search — use when you know which
    knowledge domain holds the answer. Get collection_id from GET /collections.

    For LLM consumption, set context_mode="deep" to get full H2 chapter context.

    - **collection_id**: Collection ID (GUID) to search within
    - **query**: Search query text
    - **top_k**: Number of results to return (1-100, default 10)
    - **context_mode**: "none" (raw chunk), "narrow" (H3 section), "deep" (H2 chapter)

    Returns search results with scores, content, and source information.
    """
    logger.info(
        f"Scoped collection search: collection_id={collection_id}, query='{query[:50]}...'"
    )

    col = db.query(Collection).filter(Collection.collection_id == collection_id).first()
    if not col:
        raise HTTPException(
            status_code=404, detail=f"Collection not found: {collection_id}"
        )

    try:
        searcher = create_multi_index_searcher(db)
        results = await searcher.search_collections(
            CollectionSearch(
                query=query,
                account_id=None,
                collection_id=collection_id,
                top_k=top_k,
                context_mode=context_mode,
                hf_api_token=os.getenv("HF_TOKEN"),
                node_type_filter=parse_node_type_filter(node_type_filter),
                routing_mode=routing_mode,
            )
        )

        return build_collection_search_response(
            query=query,
            account_id=col.account.account_id if col.account else None,
            collection_id=collection_id,
            results=results,
            context_mode=context_mode,
            db=db,
            extract_citation=extract_citation_from_result,
        )
    except Exception as e:
        logger.error(f"Scoped collection search failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Collection search failed: {str(e)}"
        )


@router.post("/collection", response_model=CollectionSearchResponse)
async def search_collection_by_query_param(
    collection_id: str = Query(..., description="Collection ID to search"),
    query: str = Query(..., description="Search query"),
    top_k: int = Query(10, ge=1, le=100, description="Number of results to return"),
    context_mode: str = Query(
        "none", description="Context expansion mode: none, narrow (H3), deep (H2)"
    ),
    node_type_filter: Optional[str] = Query(
        None, description="Comma-separated node types to filter (e.g., 'code,table')"
    ),
    routing_mode: str = Query("auto", description="Routing mode: auto, llm, or fast"),
    db: Session = Depends(get_db),
):
    """Query-param alias for collection-scoped search."""
    return await search_collection(
        collection_id=collection_id,
        query=query,
        top_k=top_k,
        context_mode=context_mode,
        node_type_filter=node_type_filter,
        routing_mode=routing_mode,
        db=db,
    )


