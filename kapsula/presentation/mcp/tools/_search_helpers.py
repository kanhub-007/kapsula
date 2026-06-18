"""Search helpers shared across MCP search tool modules.

Functions that are used by multiple tool registration modules:
- search_documents, search_collection → run_search_documents_text
- intelligent_search → run_intelligent_collection_search
- Background job runners → execute_search_job, execute_intelligent_search_job
- Both → log_search_miss, get_topic_card_summary
"""

import asyncio

from kapsula.infrastructure.data import (
    LibraryCard as OrmLibraryCard,
)

from ._shared import (
    _get_db,
    _get_intelligent_searcher,
    _get_multi_index_searcher,
    _hf_token,
    _parse_node_type_filter,
    _resolve_collection,
)


def log_search_miss(
    db,
    query: str,
    collection_id: str,
    result_count: int,
    results: list[dict],
) -> None:
    """Log a search that returned few results for gap detection (Phase 3)."""
    from kapsula.infrastructure.repositories.data.sql_search_miss_repository import (
        SqlSearchMissLogRepository,
    )

    top_score = results[0].get("score", 0) if results else 0.0
    SqlSearchMissLogRepository(db).log(
        collection_id=collection_id,
        query=query,
        result_count=result_count,
        top_score=top_score,
    )


def get_topic_card_summary(db, collection_db_id: int) -> str:
    """Return a summary of topic cards for the collection (Phase 3)."""
    cards = (
        db.query(OrmLibraryCard)
        .filter(
            OrmLibraryCard.collection_id == collection_db_id,
            OrmLibraryCard.card_type == "topic",
        )
        .order_by(OrmLibraryCard.importance.desc())
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
                node_type_filter=_parse_node_type_filter(node_type_filter),
                routing_mode=routing_mode,
            )
        )

        # Log search misses for gap detection (Phase 3)
        if len(results) < 3 and collection_id:
            log_search_miss(db, query, collection_id, len(results), results)

        return format_search_results(
            query, results, scope=scope, context_mode=context_mode
        )
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
    """Thin wrapper: acquire a DB session if needed and guarantee closure.

    The real work lives in :func:`_run_intelligent_collection_search` so the
    try/finally is one line regardless of how complex the body grows.
    """
    own_db = db is None
    if own_db:
        db = _get_db()
    try:
        return await _run_intelligent_collection_search(
            db=db,
            query=query,
            top_k=top_k,
            context_mode=context_mode,
            account_id=account_id,
            enable_planning=enable_planning,
            node_type_filter=node_type_filter,
        )
    finally:
        if own_db:
            db.close()


async def _run_intelligent_collection_search(
    *,
    db,
    query: str,
    top_k: int,
    context_mode: str,
    account_id: str | None,
    enable_planning: bool,
    node_type_filter: str | None,
) -> str:
    """Real body of :func:`run_intelligent_collection_search`.

    Split out so the caller's try/finally is trivial regardless of body size.
    """
    from kapsula.core.application.dto.collection_search import CollectionSearch
    from kapsula.startup import create_prepare_intelligent_search_use_case

    token = _hf_token()
    if not token:
        return "Error: HF_TOKEN not set."

    # Shared preparation (closes A6/D5): the same use case the API route uses.
    try:
        preparation = await asyncio.to_thread(
            lambda: create_prepare_intelligent_search_use_case(db).prepare(
                query, account_id, enable_planning
            )
        )
    except ValueError:
        return "No collections found."

    routed_coll = preparation.routed_collection
    search_plan = preparation.plan

    coll_searcher = _get_multi_index_searcher(db)

    async def execute_search(q: str):
        return await coll_searcher.search_collections(
            CollectionSearch(
                query=q,
                account_id=account_id or "",
                top_k=min(top_k, 100),
                context_mode=context_mode,
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
    return result_text
