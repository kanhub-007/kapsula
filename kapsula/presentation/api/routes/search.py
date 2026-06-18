"""Search routes for hybrid document search."""

import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from kapsula.core.application.dto.collection_search import CollectionSearch
from kapsula.core.application.dto.single_index_search import SingleIndexSearch
from kapsula.core.application.dto.sub_document_search import SubDocumentSearch
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
    Citation,
)

logger = get_logger(__name__)
router = APIRouter()


def extract_citation_from_result(
    result: dict, db: Session, document_id: int = None
) -> Optional[Citation]:
    """
    Extract citation information from a search result.

    Args:
        result: Search result dictionary containing chunk index and optionally sub_document_id
        db: Database session
        document_id: Document ID to filter chunks (optional but recommended)

    Returns:
        Citation object or None if citation data not available
    """
    try:
        chunk_index = result.get("index")
        if chunk_index is None:
            return None

        # Get chunk from database with proper filtering
        from kapsula.infrastructure.data import Chunk

        # Build query with available filters to avoid wrong chunk matches
        query = db.query(Chunk).filter(Chunk.chunk_index == chunk_index)

        # Add document_id filter if available
        if document_id is not None:
            query = query.filter(Chunk.document_id == document_id)

        # Add sub_document_id filter if available in result
        sub_document_id = result.get("sub_document_id")
        if sub_document_id is not None:
            query = query.filter(Chunk.sub_document_id == sub_document_id)

        chunk = query.first()

        if not chunk or not chunk.chunk_metadata:
            return None

        # Parse metadata
        metadata = json.loads(chunk.chunk_metadata)
        citation_data = metadata.get("citation")

        if not citation_data:
            return None

        return Citation(
            library_card_id=citation_data.get("library_card_id"),
            start_char=citation_data.get("start_char", 0),
            end_char=citation_data.get("end_char", 0),
            section_title=citation_data.get("section_title", ""),
            section_level=citation_data.get("section_level", ""),
        )
    except Exception as e:
        logger.warning(f"Failed to extract citation from result: {e}")
        return None


from kapsula.core.domain.text_processing import parse_node_type_filter


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


@router.post(
    "/intelligent_search/collections",
    response_model=IntelligentCollectionSearchResponse,
)
async def intelligent_search_across_collections(
    query: str = Query(..., description="Search query"),
    account_id: Optional[str] = Query(
        None, description="Account ID to search within (optional)"
    ),
    top_k: int = Query(10, ge=1, le=100, description="Number of results to return"),
    context_mode: str = Query(
        "none", description="Context expansion mode: none, narrow (H3), deep (H2)"
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
    Intelligent LLM-powered search across collections.

    The system plans sub-questions, searches each, evaluates results, and
    synthesizes a grounded answer. Best for complex questions, cross-document
    reasoning, comparisons, and analysis. Not for simple fact retrieval.

    For LLM consumption, set context_mode="deep" to get full H2 chapter context.

    - **query**: Search query text
    - **account_id**: Optional account ID to filter collections
    - **top_k**: Number of search results per sub-question (1-100, default 10)
    - **context_mode**: "none" (raw chunk), "narrow" (H3 section), "deep" (H2 chapter)
    - **enable_planning**: Decompose complex questions into sub-searches (default: True)

    Returns an LLM-generated answer grounded in search results.
    """
    logger.info(
        f"Intelligent collection search: '{query[:50]}...' (account_id={account_id}, planning={enable_planning})"
    )

    try:
        # Import routing functionality
        from kapsula.core.application.use_cases.selectors.collection_selector import (
            CollectionSelector,
        )

        # Step 1: Route to the correct collection using existing routing
        collections_query = db.query(Collection)
        if account_id:
            collections_query = collections_query.join(Collection.account).filter(
                Collection.account.has(account_id=account_id)
            )
        collections = collections_query.all()

        if not collections:
            logger.warning("No collections found")
            raise HTTPException(status_code=404, detail="No collections available")

        # Use existing routing to find the right collection
        router = CollectionSelector(create_chat_client())
        collection_metadata = []
        for coll in collections:
            card = (
                db.query(LibraryCard)
                .filter(
                    LibraryCard.collection_id == coll.id,
                    LibraryCard.level == "collection",
                )
                .first()
            )

            collection_metadata.append(
                {
                    "id": coll.id,
                    "name": coll.name,
                    "library_card_summary": (
                        card.content[:500] if card else f"Collection: {coll.name}"
                    ),
                    "document_count": len(coll.documents),
                }
            )

        routed_collection_ids = router.select(query, collection_metadata)
        routed_collection_id = (
            routed_collection_ids[0] if routed_collection_ids else collections[0].id
        )
        logger.info(f"Routed to collection ID: {routed_collection_id}")

        # Step 2: Get library cards (document structure) from the routed collection
        document_structure = []
        routed_collection = (
            db.query(Collection).filter(Collection.id == routed_collection_id).first()
        )

        if routed_collection:
            # Get all documents in this collection
            documents = (
                db.query(Document)
                .filter(Document.collection_id == routed_collection_id)
                .all()
            )

            for doc in documents:
                # Get subdocuments
                subdocs = (
                    db.query(SubDocument)
                    .filter(SubDocument.document_id == doc.id)
                    .all()
                )
                from kapsula.presentation.shared.document_structure_builder import (
                    build_document_structure_from_subdocs,
                )
                document_structure.extend(
                    build_document_structure_from_subdocs(subdocs, db)
                )

        search_plan = None

        # Step 3: Create query plan using library cards (if enabled and structure available)
        if enable_planning and document_structure:
            logger.info(
                f"Creating query plan using {len(document_structure)} sections from routed collection"
            )
            planner = create_query_planner()
            search_plan = planner.plan_document_search(
                query, document_library_card=None, document_structure=document_structure
            )
            logger.info(
                f"Query plan: {search_plan['strategy']} - {search_plan.get('reasoning', '')}"
            )

        # Step 4 & 5: Execute searches (routing per sub-question happens automatically) and aggregate
        intelligent_engine = create_intelligent_searcher()

        # Create search function that searches within the routed collection
        async def execute_search(search_query: str):
            return await create_multi_index_searcher(db).search_collections(
                CollectionSearch(
                    query=search_query,
                    account_id=account_id,
                    top_k=top_k,
                    context_mode=context_mode,
                    hf_api_token=os.getenv("HF_TOKEN"),
                )
            )

        intelligent_result = await intelligent_engine.evaluate_and_answer_with_planning(
            query=query,
            search_function=execute_search,
            max_context_length=max_context_length,
            plan=search_plan,
        )

        logger.info(
            f"Intelligent collection search completed: "
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
                    citation = extract_citation_from_result(result, db)
                    if citation:
                        all_citations.append(citation)
            else:
                # Single query mode - use only relevant result indices
                for result_index in relevant_indices:
                    if result_index < len(search_results):
                        result = search_results[result_index]
                        citation = extract_citation_from_result(result, db)
                        if citation:
                            all_citations.append(citation)

        unique_citations = collect_unique_citations(all_citations)

        return IntelligentCollectionSearchResponse(
            query=query,
            account_id=account_id,
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
        logger.error(f"Intelligent collection search failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Intelligent collection search failed: {str(e)}"
        )


@router.post("/intelligent_search/collections/stream")
async def intelligent_search_across_collections_streaming(
    query: str = Query(..., description="Search query"),
    account_id: Optional[str] = Query(
        None, description="Account ID to search within (optional)"
    ),
    top_k: int = Query(10, ge=1, le=100, description="Number of results to return"),
    context_mode: str = Query(
        "none", description="Context expansion mode: none, narrow (H3), deep (H2)"
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
    Streaming version of intelligent search across collections.

    Returns Server-Sent Events (SSE) with progress updates in real-time.

    **Response Format:** text/event-stream (Server-Sent Events)

    Each event is formatted as:
    ```
    data: <JSON object>

    ```

    **Event Types:**

    1. **planning** - Initial plan with strategy and subquestions
       ```json
       {
         "event_type": "planning",
         "data": {
           "strategy": "single_query" | "multi_query",
           "total_subquestions": <number>,
           "queries": ["query1", "query2", ...],
           "reasoning": "explanation of strategy"
         }
       }
       ```

    2. **subquestion_start** - When a subquestion starts processing
       ```json
       {
         "event_type": "subquestion_start",
         "data": {
           "subquestion_index": <number>,
           "subquestion": "the question being processed",
           "completed": <number>,
           "total": <number>
         }
       }
       ```

    3. **subquestion_complete** - When a subquestion completes with its answer
       ```json
       {
         "event_type": "subquestion_complete",
         "data": {
           "subquestion_index": <number>,
           "subquestion": "the question that was processed",
           "answer": "the answer to this subquestion",
           "has_answer": <boolean>,
           "num_results": <number>,
           "completed": <number>,
           "total": <number>
         }
       }
       ```

    4. **final_answer** - Final synthesized answer with all metadata (sent twice: once with basic data, then with citations)
       ```json
       {
         "event_type": "final_answer",
         "data": {
           "answer": "the final synthesized answer",
           "has_answer": <boolean>,
           "relevant_results": [<indices>],
           "total_evaluated": <number>,
           "plan": {
             "strategy": "single_query" | "multi_query",
             "queries": [...],
             "reasoning": "...",
             "total_unique_results": <number>,
             "sub_answers_count": <number>
           },
           "sub_answers": [
             {
               "question": "...",
               "answer": "...",
               "has_answer": <boolean>,
               "num_results": <number>
             }
           ],
           "search_results": [...],
           "citations": [...],
           "account_id": "...",
           "context_mode": "..."
         }
       }
       ```

    5. **error** - Error event if something goes wrong
       ```json
       {
         "event_type": "error",
         "data": {
           "message": "error description"
         }
       }
       ```

    **Client Usage Example (JavaScript):**
    ```javascript
    const eventSource = new EventSource('/search/intelligent_search/collections/stream?query=...');

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch(data.event_type) {
        case 'planning':
          console.log(`Plan: ${data.data.strategy} with ${data.data.total_subquestions} questions`);
          break;
        case 'subquestion_complete':
          console.log(`Subquestion ${data.data.completed}/${data.data.total}: ${data.data.answer}`);
          break;
        case 'final_answer':
          console.log('Final answer:', data.data.answer);
          eventSource.close();
          break;
        case 'error':
          console.error('Error:', data.data.message);
          eventSource.close();
          break;
      }
    };
    ```

    **Parameters:**
    - **query**: Search query text
    - **account_id**: Optional account ID to filter collections
    - **top_k**: Number of results to return per subquestion (1-100)
    - **context_mode**: Context expansion mode - "none", "narrow" (H3), "deep" (H2)
    - **max_context_length**: Maximum context length for LLM (1000-20000)
    - **enable_planning**: Enable query planning to create subquestions (default: True)
    """
    logger.info(
        f"Streaming intelligent collection search: '{query[:50]}...' (account_id={account_id}, planning={enable_planning})"
    )

    async def event_generator():
        try:
            # Import routing functionality
            from kapsula.core.application.use_cases.selectors.collection_selector import (
                CollectionSelector,
            )

            # Step 1: Route to the correct collection
            collections_query = db.query(Collection)
            if account_id:
                collections_query = collections_query.join(Collection.account).filter(
                    Collection.account.has(account_id=account_id)
                )
            collections = collections_query.all()

            if not collections:
                logger.warning("No collections found")
                yield f"data: {json.dumps({'event_type': 'error', 'data': {'message': 'No collections available'}})}\n\n"
                return

            # Use existing routing to find the right collection
            router = CollectionSelector(create_chat_client())
            collection_metadata = []
            for coll in collections:
                card = (
                    db.query(LibraryCard)
                    .filter(
                        LibraryCard.collection_id == coll.id,
                        LibraryCard.level == "collection",
                    )
                    .first()
                )

                collection_metadata.append(
                    {
                        "id": coll.id,
                        "name": coll.name,
                        "library_card_summary": (
                            card.content[:500] if card else f"Collection: {coll.name}"
                        ),
                        "document_count": len(coll.documents),
                    }
                )

            routed_collection_ids = router.select(query, collection_metadata)
            routed_collection_id = (
                routed_collection_ids[0] if routed_collection_ids else collections[0].id
            )
            logger.info(f"Routed to collection ID: {routed_collection_id}")

            # Step 2: Get library cards from the routed collection
            document_structure = []
            routed_collection = (
                db.query(Collection)
                .filter(Collection.id == routed_collection_id)
                .first()
            )

            if routed_collection:
                documents = (
                    db.query(Document)
                    .filter(Document.collection_id == routed_collection_id)
                    .all()
                )

                for doc in documents:
                    subdocs = (
                        db.query(SubDocument)
                        .filter(SubDocument.document_id == doc.id)
                        .all()
                    )
                    from kapsula.presentation.shared.document_structure_builder import (
                        build_document_structure_from_subdocs,
                    )
                    document_structure.extend(
                        build_document_structure_from_subdocs(subdocs, db)
                    )

            search_plan = None

            # Step 3: Create query plan
            if enable_planning and document_structure:
                logger.info(
                    f"Creating query plan using {len(document_structure)} sections from routed collection"
                )
                planner = create_query_planner()
                search_plan = planner.plan_document_search(
                    query,
                    document_library_card=None,
                    document_structure=document_structure,
                )
                logger.info(
                    f"Query plan: {search_plan['strategy']} - {search_plan.get('reasoning', '')}"
                )

            # Step 4 & 5: Execute searches with streaming
            intelligent_engine = create_intelligent_searcher()

            async def execute_search(search_query: str):
                # Reranker disabled — runs too slow locally
                return await create_multi_index_searcher(db).search_collections(
                    CollectionSearch(
                        query=search_query,
                        account_id=account_id,
                        top_k=top_k,
                        context_mode=context_mode,
                        hf_api_token=os.getenv("HF_TOKEN"),
                    )
                )

            # Stream events from intelligent search
            async for (
                event
            ) in intelligent_engine.evaluate_and_answer_with_planning_streaming(
                query=query,
                search_function=execute_search,
                max_context_length=max_context_length,
                plan=search_plan,
            ):
                # Send event as SSE
                yield f"data: {json.dumps(event)}\n\n"

                # If this is the final answer, extract citations
                if event["event_type"] == "final_answer":
                    all_citations = []
                    search_results = event["data"].get("search_results", [])

                    if search_results:
                        for result in search_results:
                            citation = extract_citation_from_result(result, db)
                            if citation:
                                all_citations.append(citation)

                    unique_citations = collect_unique_citations(all_citations)

                    # Add citations to the final data
                    event["data"]["citations"] = [c.model_dump() for c in unique_citations]
                    event["data"]["account_id"] = account_id
                    event["data"]["context_mode"] = context_mode

                    # Send updated final answer with citations
                    yield f"data: {json.dumps(event)}\n\n"

            logger.info("Streaming intelligent collection search completed")

        except Exception as e:
            logger.error(
                f"Streaming intelligent collection search failed: {e}", exc_info=True
            )
            yield f"data: {json.dumps({'event_type': 'error', 'data': {'message': str(e)}})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/search/{job_id}", response_model=SearchResponse)
async def search_document(
    job_id: str,
    query: str = Query(..., description="Search query"),
    top_k: int = Query(10, ge=1, le=100, description="Number of results to return"),
    context_mode: str = Query(
        "none", description="Context expansion mode: none, narrow (H3), deep (H2)"
    ),
    node_type_filter: Optional[str] = Query(
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
                    hf_api_token=os.getenv("HF_TOKEN"),
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
        logger.error(f"Search failed for {job_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.post("/intelligent_search/{job_id}", response_model=IntelligentSearchResponse)
async def intelligent_search_document(
    job_id: str,
    query: str = Query(..., description="Search query"),
    top_k: int = Query(10, ge=1, le=100, description="Number of results to return"),
    context_mode: str = Query(
        "none", description="Context expansion mode: none, narrow (H3), deep (H2)"
    ),
    node_type_filter: Optional[str] = Query(
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
                build_document_structure_from_subdocs,
                build_document_structure_from_document,
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
                        hf_api_token=os.getenv("HF_TOKEN"),
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
        logger.error(f"Intelligent search failed for {job_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Intelligent search failed: {str(e)}"
        )
