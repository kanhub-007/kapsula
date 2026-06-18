"""Search helpers shared across MCP search tool modules.

Functions that are used by multiple tool registration modules:
- search_documents, search_collection → run_search_documents_text
- intelligent_search → run_intelligent_collection_search
- Background job runners → execute_search_job, execute_intelligent_search_job
- Both → log_search_miss, get_topic_card_summary
"""

import asyncio

from kapsula.infrastructure.data import (
    Account,
    Collection,
    Document,
    LibraryCard,
    SubDocument,
    SearchMissLog,
)

from ._shared import (
    _get_db,
    _hf_token,
    _parse_node_type_filter,
    _get_chat_client,
    _get_query_planner,
    _get_multi_index_searcher,
    _get_intelligent_searcher,
    _resolve_collection,
    _get_search_job_manager,
)


def log_search_miss(
    db,
    query: str,
    collection_id: str,
    result_count: int,
    results: list[dict],
) -> None:
    """Log a search that returned few results for gap detection (Phase 3)."""
    top_score = results[0].get("score", 0) if results else 0.0
    miss = SearchMissLog(
        collection_id=collection_id,
        query=query[:500],
        result_count=result_count,
        top_score=top_score,
    )
    db.add(miss)
    db.commit()


def get_topic_card_summary(db, collection_db_id: int) -> str:
    """Return a summary of topic cards for the collection (Phase 3)."""
    cards = (
        db.query(LibraryCard)
        .filter(
            LibraryCard.collection_id == collection_db_id,
            LibraryCard.card_type == "topic",
        )
        .order_by(LibraryCard.importance.desc())
        .limit(5)
        .all()
    )
    if not cards:
        return ""

    lines = []
    for card in cards:
        imp = card.importance or 0.5
        preview = card.content[:300].replace(chr(10), " ").strip()
        lines.append(f"[{card.title}] (importance: {imp:.1f}): {preview}")
    return chr(10).join(lines)


async def run_search_documents_text(
    query: str,
    top_k: int = 10,
    context_mode: str = "none",
    account_id: str | None = None,
    collection_id: str | None = None,
    node_type_filter: str | None = None,
    routing_mode: str = "auto",
) -> str:
    from kapsula.core.application.dto.collection_search import CollectionSearch
    from kapsula.presentation.mcp.search_presenter import format_search_results

    db = _get_db()
    try:
        if collection_id:
            col = _resolve_collection(db, collection_id)
            if not col:
                return f"Collection not found: {collection_id}"
            scope = f"in collection '{col.name}'"
        else:
            scope = ""

        searcher = _get_multi_index_searcher(db)
        results = await searcher.search_collections(
            CollectionSearch(
                query=query,
                account_id=account_id or None,
                collection_id=collection_id,
                top_k=min(top_k, 100),
                context_mode=context_mode,
                hf_api_token=_hf_token(),
                node_type_filter=_parse_node_type_filter(node_type_filter),
                routing_mode=routing_mode,
            )
        )

        # Log search misses for gap detection (Phase 3)
        if len(results) < 3 and collection_id:
            log_search_miss(db, query, collection_id, len(results), results)

        return format_search_results(query, results, scope=scope, context_mode=context_mode)
    finally:
        db.close()


async def run_intelligent_collection_search(
    query: str,
    top_k: int,
    context_mode: str,
    account_id: str | None,
    enable_planning: bool,
    node_type_filter: str | None,
    db=None,
) -> str:
    from kapsula.core.application.dto.collection_search import CollectionSearch
    from kapsula.core.application.use_cases.selectors.collection_selector import (
        CollectionSelector,
    )

    own_db = db is None
    if own_db:
        db = _get_db()
    token = _hf_token()
    if not token:
        return "Error: HF_TOKEN not set."

    def _db_work():
        q = db.query(Collection)
        if account_id:
            q = q.join(Account).filter(Account.account_id == account_id)
        collections = q.all()
        if not collections:
            return None, None, None, None

        router = CollectionSelector(_get_chat_client())
        meta = []
        for c in collections:
            card = (
                db.query(LibraryCard)
                .filter(
                    LibraryCard.collection_id == c.id,
                    LibraryCard.level == "collection",
                )
                .first()
            )
            meta.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "library_card_summary": card.content[:500] if card else c.name,
                    "document_count": len(c.documents),
                }
            )

        routed_ids = router.select(query, meta)
        routed_id = routed_ids[0] if routed_ids else collections[0].id
        routed_coll = db.query(Collection).filter(Collection.id == routed_id).first()

        from kapsula.presentation.shared.document_structure_builder import (
            build_document_structure_from_subdocs,
        )
        document_structure = []
        if routed_coll:
            for doc in routed_coll.documents:
                document_structure.extend(
                    build_document_structure_from_subdocs(doc.sub_documents, db)
                )

        search_plan = None
        if enable_planning and document_structure:
            planner = _get_query_planner()
            search_plan = planner.plan_document_search(
                query, document_structure=document_structure
            )

        return collections, routed_coll, document_structure, search_plan

    result_tuple = await asyncio.to_thread(_db_work)
    if result_tuple[0] is None:
        return "No collections found."
    collections, routed_coll, document_structure, search_plan = result_tuple

    coll_searcher = _get_multi_index_searcher(db)

    async def execute_search(q: str):
        return await coll_searcher.search_collections(
            CollectionSearch(
                query=q,
                account_id=account_id or "",
                top_k=min(top_k, 100),
                context_mode=context_mode,
                hf_api_token=token,
            )
        )

    engine = _get_intelligent_searcher()
    result = await engine.evaluate_and_answer_with_planning(
        query=query,
        search_function=execute_search,
        max_context_length=8000,
        plan=search_plan,
    )

    parts = []

    # Include topic cards as knowledge overview (Phase 3)
    if routed_coll:
        topic_summary = get_topic_card_summary(db, routed_coll.id)
        if topic_summary:
            parts.append("--- Knowledge Overview (synthesized) ---")
            parts.append(topic_summary)
            parts.append("")

    plan_info = result.get("plan", {})
    if plan_info:
        parts.append(f"Strategy: {plan_info.get('strategy', '?')}")
        parts.append(f"Sub-questions: {len(plan_info.get('queries', []))}")
        parts.append("")
    parts.append(result.get("answer", "No answer generated."))
    result_text = "\n".join(parts)
    if own_db:
        db.close()
    return result_text
