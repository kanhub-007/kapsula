"""Search routes."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from kapsula.core.application.dto.single_document_search import (
    SingleDocumentSearch,
)
from kapsula.core.domain.text_processing import parse_node_type_filter
from kapsula.infrastructure.data.connection import get_db
from kapsula.infrastructure.data.tables.document import Document
from kapsula.infrastructure.data.tables.library_card import LibraryCard
from kapsula.infrastructure.data.tables.sub_document import SubDocument
from kapsula.infrastructure.logging_config import get_logger
from kapsula.presentation.api.search_presenter import (
    collect_intelligent_citations,
    collect_unique_citations,
    to_search_result,
)
from kapsula.startup import (
    create_intelligent_searcher,
    create_multi_index_searcher,
    create_query_planner,
)

from .._http import internal_server_error
from ..models import (
    IntelligentSearchResponse,
    SearchPlan,
    SearchResponse,
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

    node_types = parse_node_type_filter(node_type_filter) if node_type_filter else None
    if node_type_filter:
        logger.info(f"Node type filter applied: {node_types}")

    from kapsula.startup import create_search_single_document_use_case

    try:
        results = await create_search_single_document_use_case(db).execute(
            db=db,
            job_id=job_id,
            query=query,
            top_k=top_k,
            context_mode=context_mode,
            node_type_filter=node_types,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from exc
        if "not ready" in msg:
            raise HTTPException(status_code=400, detail=msg) from exc
        raise HTTPException(status_code=500, detail=msg) from exc

    logger.info(
        f"Search completed for {job_id}: {len(results)} results "
        f"(context={context_mode}, node_filter={node_types})"
    )

    # Build the response via the shared presenter (closes H7).
    search_results = []
    all_citations = []
    for result in results:
        citation = extract_citation_from_result(
            result, db, document_id=result.document_id
        )
        search_results.append(to_search_result(result, citation))
        all_citations.append(citation)
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
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Document not ready for search. Status: {document.status}",
        )

    subdocs = db.query(SubDocument).filter(SubDocument.document_id == document.id).all()
    multi_searcher = create_multi_index_searcher(db)

    try:
        search_plan = (
            _build_document_search_plan(db, document, subdocs, query)
            if enable_planning
            else None
        )

        async def execute_search(search_query: str):
            # Unified dispatch (closes H5/H6): no more subdoc/flat branch here.
            return await multi_searcher.search_document(
                SingleDocumentSearch(
                    query=search_query,
                    document_id=document.id,
                    faiss_path=document.faiss_index_path,
                    bm25_path=document.bm25_index_path,
                    top_k=top_k,
                    context_mode=context_mode,
                    node_type_filter=node_types,
                )
            )

        intelligent_engine = create_intelligent_searcher()
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

        response_plan = (
            SearchPlan(**intelligent_result["plan"])
            if intelligent_result.get("plan")
            else None
        )
        response_sub_answers = None
        if intelligent_result.get("sub_answers"):
            from ..models import SubAnswer

            response_sub_answers = [
                SubAnswer(**sub_answer)
                for sub_answer in intelligent_result["sub_answers"]
            ]

        unique_citations = collect_intelligent_citations(
            intelligent_result, db, extract_citation_from_result, document.id
        )

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
        raise internal_server_error("Intelligent search failed") from e


def _build_document_search_plan(db, document, subdocs, query: str):
    """Plan sub-questions for a document search using its structure (H6).

    Extracted from ``intelligent_search_document`` so the route body stays
    under the size limit. Returns None when no structure is available.
    """
    library_cards = []
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
                json.loads(doc_card.extra_metadata) if doc_card.extra_metadata else {}
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

    if not document_structure:
        return None

    logger.info(
        "Creating query plan using document structure from %s section(s)",
        len(document_structure),
    )
    planner = create_query_planner()
    plan = planner.plan_document_search(
        query,
        document_library_card=library_cards[0] if library_cards else None,
        document_structure=document_structure,
    )
    logger.info("Query plan: %s - %s", plan["strategy"], plan.get("reasoning", ""))
    return plan
