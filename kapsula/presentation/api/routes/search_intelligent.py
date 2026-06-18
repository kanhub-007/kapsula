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


