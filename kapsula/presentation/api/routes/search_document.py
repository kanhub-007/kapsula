"""Search routes."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from kapsula.core.application.dto.single_index_search import SingleIndexSearch
from kapsula.core.application.dto.sub_document_search import SubDocumentSearch
from kapsula.infrastructure.data.connection import get_db
from kapsula.infrastructure.data.tables.document import Document
from kapsula.infrastructure.data.tables.library_card import LibraryCard
from kapsula.infrastructure.data.tables.sub_document import SubDocument
from kapsula.infrastructure.logging_config import get_logger
from kapsula.presentation.api.search_presenter import collect_unique_citations
from kapsula.startup import (
    create_intelligent_searcher,
    create_multi_index_searcher,
    create_query_planner,
)

from ..models import (
    IntelligentSearchResponse,
    SearchPlan,
    SearchResponse,
    SearchResult,
)
from .search_helpers import extract_citation_from_result

logger = get_logger(__name__)
router = APIRouter()


@router.post("/search/{job_id}", response_model=SearchResponse)
async def search_document(
    job_id: str,
    query: str = Query(..., description="Search query"),
    top_k: int = Query(10, ge=1, le=100, description="Number of results to return"),
    context_mode: str = Query(
        "none", description="Context expansion mode: none, narrow (H3), deep (H2)"
    ),
    node_type_filter: str | None = Query(
        None, description="Comma-separated node types to filter (e.g., 'code,table')"
    ),
    db: Session = Depends(get_db),
):
    """
    Search within a specific document using hybrid (FAISS+BM25) retrieval.

    Most precise scope — use when you know exactly which document contains
    the answer. For broader searches, use /search/collections/{collection_id}.
    Get job_id from GET /collections/{collection_id}/documents.

    For LLM consumption, set context_mode="deep" to get full H2 chapter context.

    - **job_id**: Job ID (GUID) of the document to search
    - **query**: Search query text
    - **top_k**: Number of results to return (1-100, default 10)
    - **context_mode**: "none" (raw chunk), "narrow" (H3 section), "deep" (H2 chapter)
    - **node_type_filter**: Filter by content type: "code", "table", "text"

    Returns search results with scores, content, and citations.
    """
    logger.info(f"Search request for job {job_id}: '{query[:50]}...'")

    # Parse node_type_filter
    node_types = None
    if node_type_filter:
        node_types = [nt.strip() for nt in node_type_filter.split(",")]
        logger.info(f"Node type filter applied: {node_types}")

    # Find document
    document = db.query(Document).filter(Document.job_id == job_id).first()
    if not document:
        logger.warning(f"Document not found: {job_id}")
        raise HTTPException(status_code=404, detail="Document not found")

    # Check if document is completed
    if document.status != "completed":
        logger.warning(
            f"Document {job_id} not ready for search, status: {document.status}"
        )
        raise HTTPException(
            status_code=400,
            detail=f"Document not ready for search. Status: {document.status}",
        )

    # Check if document uses sub-document architecture
    subdocs = db.query(SubDocument).filter(SubDocument.document_id == document.id).all()

    # Perform search
    try:
        if subdocs:
            # Use new multi-index search with LLM routing
            logger.info(
                f"Using multi-index search for document {job_id} ({len(subdocs)} sub-documents)"
            )
            searcher = create_multi_index_searcher(db)
            results = await searcher.search_subdocuments(
                SubDocumentSearch(
                    query=query,
                    document_id=document.id,
                    top_k=top_k,
                    context_mode=context_mode,
                    node_type_filter=node_types,
                )
            )
        else:
            # Use legacy single-index search
            logger.info(f"Using legacy single-index search for document {job_id}")

            # Check if indexes exist
            if not document.faiss_index_path or not document.bm25_index_path:
                logger.error(f"Document {job_id} missing search indexes")
                raise HTTPException(
                    status_code=500,
                    detail="Search indexes not available for this document",
                )

            results = await create_multi_index_searcher(db).search_single_index(
                SingleIndexSearch(
                    query=query,
                    faiss_path=document.faiss_index_path,
                    bm25_path=document.bm25_index_path,
                    document_id=document.id,
                    top_k=top_k,
                    context_mode=context_mode,
                    node_type_filter=node_types,
                )
            )

        logger.info(
            f"Search completed for {job_id}: {len(results)} results (context={context_mode}, node_filter={node_types})"
        )

        # Convert to response format and extract citations
        search_results = []
        all_citations = []

        for result in results:
            citation = extract_citation_from_result(result, db, document_id=document.id)
            search_results.append(
                SearchResult(
                    index=result["index"],
                    content=result.get(
                        "expanded_content", result["content"]
                    ),  # Use expanded if available
                    score=result.get("score", 0.0),
                    dense_score=result.get("dense_score", 0.0),
                    sparse_score=result.get("sparse_score", 0.0),
                    rerank_score=result.get(
                        "rerank_score"
                    ),  # Include rerank score if available
                    sub_document_key=result.get(
                        "sub_document_key"
                    ),  # Include sub-document source
                    contributing_chunks=result.get(
                        "contributing_chunks"
                    ),  # Include aggregated chunk info
                    parent_hash=result.get(
                        "parent_hash"
                    ),  # Include parent hash for context expansion
                    citation=citation,  # Add citation to individual result
                )
            )
            all_citations.append(citation)

        # Collect unique citations
        unique_citations = collect_unique_citations(all_citations)

        return SearchResponse(
            job_id=job_id,
            query=query,
            total_results=len(search_results),
            results=search_results,
            context_mode=context_mode,
            node_type_filter=node_types,
            citations=unique_citations,
        )

    except Exception as e:
        logger.exception(f"Search failed for {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.post("/intelligent_search/{job_id}", response_model=IntelligentSearchResponse)
async def intelligent_search_document(
    job_id: str,
    query: str = Query(..., description="Search query"),
    top_k: int = Query(10, ge=1, le=100, description="Number of results to return"),
    context_mode: str = Query(
        "none", description="Context expansion mode: none, narrow (H3), deep (H2)"
    ),
    node_type_filter: str | None = Query(
        None, description="Comma-separated node types to filter (e.g., 'code,table')"
    ),
    max_context_length: int = Query(
        8000, ge=1000, le=20000, description="Maximum context length for LLM evaluation"
    ),
    enable_planning: bool = Query(
        True, description="Enable query planning with LLM (default: True)"
    ),
    db: Session = Depends(get_db),
):
    """
    Intelligent LLM-powered search within a single document.

    Analyzes the document structure via library cards, plans sub-questions,
    searches, and synthesizes a grounded answer. Use for reasoning about a
    specific document's content.

    For LLM consumption, set context_mode="deep" to get full H2 chapter context.

    - **job_id**: Job ID (GUID) of the document to search
    - **query**: Search query text
    - **top_k**: Number of search results per sub-question (1-100, default 10)
    - **context_mode**: "none" (raw chunk), "narrow" (H3 section), "deep" (H2 chapter)
    - **enable_planning**: Decompose complex questions into sub-searches (default: True)

    Returns an LLM-generated answer grounded in search results.
    """
    logger.info(
        f"Intelligent search request for job {job_id}: '{query[:50]}...' (planning={enable_planning})"
    )

    # Parse node_type_filter
    node_types = None
    if node_type_filter:
        node_types = [nt.strip() for nt in node_type_filter.split(",")]
        logger.info(f"Node type filter applied: {node_types}")

    # Find document
    document = db.query(Document).filter(Document.job_id == job_id).first()
    if not document:
        logger.warning(f"Document not found: {job_id}")
        raise HTTPException(status_code=404, detail="Document not found")

    # Check if document is completed
    if document.status != "completed":
        logger.warning(
            f"Document {job_id} not ready for search, status: {document.status}"
        )
        raise HTTPException(
            status_code=400,
            detail=f"Document not ready for search. Status: {document.status}",
        )

    # Check if document uses sub-document architecture
    subdocs = db.query(SubDocument).filter(SubDocument.document_id == document.id).all()

    # Perform search
    try:
        search_plan = None

        # Step 1: Query planning (if enabled)
        if enable_planning:
            # Fetch library cards for planning
            library_cards = []

            # Get document-level library card
            doc_card = (
                db.query(LibraryCard)
                .filter(
                    LibraryCard.document_id == document.id,
                    LibraryCard.level == "document",
                )
                .first()
            )

            if doc_card:
                try:
                    metadata = (
                        json.loads(doc_card.extra_metadata)
                        if doc_card.extra_metadata
                        else {}
                    )
                    library_cards.append(
                        {
                            "title": doc_card.title,
                            "summary": metadata.get("summary", doc_card.content[:200]),
                        }
                    )
                except Exception:
                    library_cards.append(
                        {"title": doc_card.title, "summary": doc_card.content[:200]}
                    )

            # Get document structure from library cards (H1, H2, H3 hierarchy)
            from kapsula.presentation.shared.document_structure_builder import (
                build_document_structure_from_document,
                build_document_structure_from_subdocs,
            )

            if subdocs:
                document_structure = build_document_structure_from_subdocs(subdocs, db)
            else:
                document_structure = build_document_structure_from_document(
                    document_id=document.id,
                    fallback_name=document.filename,
                    db=db,
                    limit=30,
                )

            if document_structure:
                logger.info(
                    f"Creating query plan using document structure from {len(document_structure)} section(s)"
                )
                planner = create_query_planner()
                search_plan = planner.plan_document_search(
                    query,
                    document_library_card=library_cards[0] if library_cards else None,
                    document_structure=document_structure,
                )
                logger.info(
                    f"Query plan: {search_plan['strategy']} - {search_plan.get('reasoning', '')}"
                )

        # Step 2: Execute search with or without planning
        intelligent_engine = create_intelligent_searcher()

        # Create search function closure
        async def execute_search(search_query: str):
            if subdocs:
                # Use new multi-index search with LLM routing
                searcher = create_multi_index_searcher(db)
                return await searcher.search_subdocuments(
                    SubDocumentSearch(
                        query=search_query,
                        document_id=document.id,
                        top_k=top_k,
                        context_mode=context_mode,
                    )
                )
            else:
                # Use legacy single-index search
                if not document.faiss_index_path or not document.bm25_index_path:
                    raise HTTPException(
                        status_code=500,
                        detail="Search indexes not available for this document",
                    )

                return await create_multi_index_searcher(db).search_single_index(
                    SingleIndexSearch(
                        query=search_query,
                        faiss_path=document.faiss_index_path,
                        bm25_path=document.bm25_index_path,
                        document_id=document.id,
                        top_k=top_k,
                        context_mode=context_mode,
                    )
                )

        intelligent_result = await intelligent_engine.evaluate_and_answer_with_planning(
            query=query,
            search_function=execute_search,
            max_context_length=max_context_length,
            plan=search_plan,
        )

        logger.info(
            f"Intelligent search completed for {job_id}: "
            f"has_answer={intelligent_result['has_answer']}, "
            f"evaluated={intelligent_result['total_evaluated']} results"
        )

        # Build response
        response_plan = None
        if intelligent_result.get("plan"):
            response_plan = SearchPlan(**intelligent_result["plan"])

        # Convert sub_answers to SubAnswer models
        response_sub_answers = None
        if intelligent_result.get("sub_answers"):
            from ..models import SubAnswer

            response_sub_answers = [
                SubAnswer(**sub_answer)
                for sub_answer in intelligent_result["sub_answers"]
            ]

        # Extract citations from relevant results
        # Note: relevant_results are indices into the search results array
        # The intelligent search engine returns the search results for us
        all_citations = []
        search_results = intelligent_result.get("search_results", [])

        if search_results:
            relevant_indices = intelligent_result.get("relevant_results", [])

            # If relevant_results is empty (multi-query planning mode), extract citations from all results
            if not relevant_indices:
                logger.info(
                    "No relevant_results indices (planning mode), extracting citations from all search results"
                )
                for result in search_results:
                    citation = extract_citation_from_result(
                        result, db, document_id=document.id
                    )
                    if citation:
                        all_citations.append(citation)
            else:
                # Single query mode - use only relevant result indices
                for result_index in relevant_indices:
                    if result_index < len(search_results):
                        result = search_results[result_index]
                        citation = extract_citation_from_result(
                            result, db, document_id=document.id
                        )
                        if citation:
                            all_citations.append(citation)

        unique_citations = collect_unique_citations(all_citations)

        return IntelligentSearchResponse(
            job_id=job_id,
            query=query,
            answer=intelligent_result["answer"],
            has_answer=intelligent_result["has_answer"],
            relevant_results=intelligent_result["relevant_results"],
            total_evaluated=intelligent_result["total_evaluated"],
            context_mode=context_mode,
            plan=response_plan,
            sub_answers=response_sub_answers,
            citations=unique_citations,
        )

    except Exception as e:
        logger.exception(f"Intelligent search failed for {job_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Intelligent search failed: {str(e)}"
        )
