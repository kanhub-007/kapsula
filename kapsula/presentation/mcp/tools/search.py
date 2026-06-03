"""MCP search tools — all search variants."""

import asyncio

from fastmcp import FastMCP

from kapsula.infrastructure.data import (
    SessionLocal,
    Document,
    Collection,
    Account,
    LibraryCard,
    SubDocument,
)
from ._shared import (
    _get_db,
    _hf_token,
    _parse_node_type_filter,
    _get_chat_client,
    _get_query_planner,
    _get_embedder,
    _get_reranker,
    _get_multi_index_searcher,
    _get_intelligent_searcher,
    _resolve_collection,
    _get_search_job_manager,
)


# ── shared search helpers ──────────────────────────────────


def _log_search_miss(
    db,
    query: str,
    collection_id: str,
    result_count: int,
    results: list[dict],
) -> None:
    """Log a search that returned few results for gap detection (Phase 3)."""
    from kapsula.infrastructure.data import SearchMissLog

    top_score = results[0].get("score", 0) if results else 0.0
    miss = SearchMissLog(
        collection_id=collection_id,
        query=query[:500],
        result_count=result_count,
        top_score=top_score,
    )
    db.add(miss)
    db.commit()




async def _run_search_documents_text(
    query: str,
    top_k: int = 10,
    rerank: bool = False,
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
                rerank=False,
                context_mode=context_mode,
                hf_api_token=_hf_token(),
                node_type_filter=_parse_node_type_filter(node_type_filter),
                routing_mode=routing_mode,
            )
        )

        # Log search misses for gap detection (Phase 3)
        if len(results) < 3 and collection_id:
            _log_search_miss(db, query, collection_id, len(results), results)

        return format_search_results(query, results, scope=scope, context_mode=context_mode)
    finally:
        db.close()


async def _run_intelligent_collection_search(
    query: str,
    top_k: int,
    context_mode: str,
    account_id: str | None,
    enable_planning: bool,
    rerank: bool,
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

        document_structure = []
        if routed_coll:
            for doc in routed_coll.documents:
                for subdoc in doc.sub_documents:
                    cards = (
                        db.query(LibraryCard)
                        .filter(
                            LibraryCard.sub_document_id == subdoc.id,
                            LibraryCard.level.in_(["level_1", "level_2", "level_3"]),
                        )
                        .order_by(LibraryCard.level.desc())
                        .limit(20)
                        .all()
                    )
                    if cards:
                        document_structure.append(
                            {
                                "subdocument_name": subdoc.breadcrumb_key,
                                "sections": [
                                    {"level": c.level, "title": c.title} for c in cards
                                ],
                            }
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
                rerank=False,
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


# ── tool registration ─────────────────────────────────────


def register_search_tools(mcp: FastMCP):
    from kapsula.presentation.mcp.search_jobs import SearchJob
    from kapsula.infrastructure.logging_config import get_logger

    logger = get_logger(__name__)

    async def _execute_search_job(job: SearchJob) -> None:
        manager = _get_search_job_manager()
        manager.update(job, status="running", progress="Search running")
        try:
            result = await _run_search_documents_text(**job.params)
            manager.update(job, status="completed", progress="Search completed", result=result)
        except asyncio.CancelledError:
            manager.update(job, status="cancelled", progress="Search cancelled")
            raise
        except Exception as exc:
            logger.error("Background search job failed: %s", exc, exc_info=True)
            manager.update(job, status="failed", progress="Search failed", error=str(exc))

    async def _execute_intelligent_search_job(job: SearchJob) -> None:
        manager = _get_search_job_manager()
        manager.update(job, status="running", progress="Intelligent search running")
        try:
            result = await _run_intelligent_collection_search(
                query=job.params["query"],
                top_k=job.params.get("top_k", 10),
                context_mode=job.params.get("context_mode", "none"),
                account_id=job.params.get("account_id"),
                enable_planning=job.params.get("enable_planning", True),
                rerank=job.params.get("rerank", False),
                node_type_filter=job.params.get("node_type_filter"),
            )
            manager.update(job, status="completed", progress="Intelligent search completed", result=result)
        except asyncio.CancelledError:
            manager.update(job, status="cancelled", progress="Intelligent search cancelled")
            raise
        except Exception as exc:
            logger.error("Background intelligent search job failed: %s", exc, exc_info=True)
            manager.update(job, status="failed", progress="Intelligent search failed", error=str(exc))

    @mcp.tool(
        name="search_documents",
        description=(
            "RAW CHUNK RETRIEVAL — returns ranked chunks with scores; YOU judge relevance. "
            "Scores: 0.0-1.0 (>0.5 good, >0.7 strong, <0.3 noise). "
            "Best for: fact lookup with known keywords, finding exact text, citing specific passages. "
            "NOT for: complex reasoning or comparisons — use intelligent_search for those. "
            "context_mode: 'none'=raw chunk, 'narrow'=H3 section, 'deep'=H2 chapter (use 'deep' for LLM). "
            "node_type_filter: comma-separated like 'table,code' to restrict content types."
        ),
    )
    async def search_documents(
        query: str,
        top_k: int = 10,
        rerank: bool = False,
        context_mode: str = "none",
        account_id: str | None = None,
        node_type_filter: str | None = None,
        routing_mode: str = "auto",
    ) -> str:
        return await _run_search_documents_text(
            query=query,
            top_k=top_k,
            rerank=rerank,
            context_mode=context_mode,
            account_id=account_id,
            node_type_filter=node_type_filter,
            routing_mode=routing_mode,
        )

    @mcp.tool(
        name="search_collection",
        description=(
            "Search within ONE collection (knowledge domain) by collection_id. "
            "Faster and more precise than search_documents because it's scoped to a single domain. "
            "Use when you know which collection holds the relevant knowledge (e.g., search only 'Dog Training' "
            "docs, not all collections). context_mode: 'none'=raw chunk, 'narrow'=H3 section, 'deep'=H2 chapter. "
            "node_type_filter: comma-separated like 'table,code'. Get collection_id from list_collections or get_account."
        ),
    )
    async def search_collection(
        collection_id: str,
        query: str,
        top_k: int = 10,
        rerank: bool = False,
        context_mode: str = "none",
        node_type_filter: str | None = None,
        routing_mode: str = "auto",
    ) -> str:
        return await _run_search_documents_text(
            query=query,
            top_k=top_k,
            rerank=rerank,
            context_mode=context_mode,
            collection_id=collection_id,
            node_type_filter=node_type_filter,
            routing_mode=routing_mode,
        )

    @mcp.tool(
        name="start_search_documents",
        description=(
            "Start a background hybrid search and return a search_job_id for polling. "
            "Use this for long-running searches where you want to poll progress asynchronously. "
            "After starting, use get_search_progress(job_id) to check status and "
            "get_search_results(job_id) when status='completed'. "
            "context_mode: 'none'/'narrow'/'deep'. node_type_filter: comma-separated like 'table,code'."
        ),
    )
    async def start_search_documents(
        query: str,
        top_k: int = 10,
        context_mode: str = "none",
        account_id: str | None = None,
        collection_id: str | None = None,
        routing_mode: str = "auto",
        rerank: bool = False,
        node_type_filter: str | None = None,
    ) -> str:
        job = _get_search_job_manager().start(
            params={
                "query": query,
                "top_k": top_k,
                "context_mode": context_mode,
                "account_id": account_id,
                "collection_id": collection_id,
                "routing_mode": routing_mode,
                "rerank": rerank,
                "node_type_filter": node_type_filter,
            },
            runner=_execute_search_job,
        )
        return (
            "Search job started.\n"
            f"  search_job_id: {job.job_id}\n"
            f"  status: {job.status}\n"
            "Use get_search_progress and get_search_results to poll it."
        )

    @mcp.tool(
        name="get_search_progress",
        description="Get status and progress for a background search job.",
    )
    def get_search_progress(search_job_id: str) -> str:
        job = _get_search_job_manager().get(search_job_id)
        if not job:
            return f"Search job not found: {search_job_id}"
        return (
            f"Search job: {job.job_id}\n"
            f"status: {job.status}\n"
            f"progress: {job.progress}\n"
            f"created_at: {job.created_at.isoformat()}\n"
            f"updated_at: {job.updated_at.isoformat()}"
            + (f"\nerror: {job.error}" if job.error else "")
        )

    @mcp.tool(
        name="get_search_results",
        description="Get results for a completed background search job.",
    )
    def get_search_results(search_job_id: str) -> str:
        job = _search_job_manager.get(search_job_id)
        if not job:
            return f"Search job not found: {search_job_id}"
        if job.status == "completed":
            return job.result or "No results found."
        if job.status == "failed":
            return f"Search job failed: {job.error or 'unknown error'}"
        if job.status == "cancelled":
            return "Search job was cancelled."
        return (
            f"Search job not complete yet. status={job.status}, progress={job.progress}"
        )

    @mcp.tool(
        name="cancel_search",
        description="Cancel a running background search job where practical.",
    )
    def cancel_search(search_job_id: str) -> str:
        job = _search_job_manager.get(search_job_id)
        if not job:
            return f"Search job not found: {search_job_id}"
        if job.status in {"completed", "failed", "cancelled"}:
            return f"Search job already {job.status}."
        _search_job_manager.cancel(search_job_id)
        return f"Cancellation requested for search_job_id: {search_job_id}"

    @mcp.tool(
        name="start_intelligent_search",
        description=(
            "Start a background intelligent (LLM-powered) search and return a search_job_id. "
            "Poll with get_intelligent_search_progress(job_id) and retrieve with "
            "get_intelligent_search_results(job_id) when status='completed'. "
            "This is the async version of intelligent_search — use for complex queries "
            "that may take time. context_mode: 'none'/'narrow'/'deep'."
        ),
    )
    async def start_intelligent_search(
        query: str,
        top_k: int = 10,
        context_mode: str = "none",
        account_id: str | None = None,
        enable_planning: bool = True,
        rerank: bool = False,
        node_type_filter: str | None = None,
    ) -> str:
        job = _get_search_job_manager().start(
            params={
                "query": query,
                "top_k": top_k,
                "context_mode": context_mode,
                "account_id": account_id,
                "enable_planning": enable_planning,
                "rerank": rerank,
                "node_type_filter": node_type_filter,
            },
            runner=_execute_intelligent_search_job,
        )
        return (
            "Intelligent search job started.\n"
            f"  search_job_id: {job.job_id}\n"
            f"  status: {job.status}\n"
            "Use get_intelligent_search_progress and "
            "get_intelligent_search_results to poll it."
        )

    @mcp.tool(
        name="get_intelligent_search_progress",
        description="Get status and progress for a background intelligent search job.",
    )
    def get_intelligent_search_progress(search_job_id: str) -> str:
        job = _get_search_job_manager().get(search_job_id)
        if not job:
            return f"Search job not found: {search_job_id}"
        return (
            f"Search job: {job.job_id}\n"
            f"status: {job.status}\n"
            f"progress: {job.progress}\n"
            f"created_at: {job.created_at.isoformat()}\n"
            f"updated_at: {job.updated_at.isoformat()}"
            + (f"\nerror: {job.error}" if job.error else "")
        )

    @mcp.tool(
        name="get_intelligent_search_results",
        description="Get results for a completed background intelligent search job.",
    )
    def get_intelligent_search_results(search_job_id: str) -> str:
        job = _search_job_manager.get(search_job_id)
        if not job:
            return f"Search job not found: {search_job_id}"
        if job.status == "completed":
            return job.result or "No results found."
        if job.status == "failed":
            return f"Search job failed: {job.error or 'unknown error'}"
        if job.status == "cancelled":
            return "Search job was cancelled."
        return (
            f"Search job not complete yet. status={job.status}, progress={job.progress}"
        )

    @mcp.tool(
        name="intelligent_search",
        description=(
            "AI-SYNTHESIZED ANSWER — the system plans, searches, and reasons for you. "
            "Returns a grounded answer with reasoning, not raw chunks. "
            "Best for: complex questions, cross-document reasoning, comparisons, analysis, "
            "or when you do not know exact search terms. "
            "NOT for: simple fact retrieval (what is X?) — use search_collection instead; "
            "it is faster and gives you exact citations. "
            "context_mode: none/narrow/deep. enable_planning=True (default) "
            "decomposes complex questions into sub-searches for better coverage."
        ),
    )
    async def intelligent_search(
        query: str,
        top_k: int = 10,
        context_mode: str = "none",
        account_id: str | None = None,
        enable_planning: bool = True,
        rerank: bool = False,
        node_type_filter: str | None = None,
    ) -> str:
        db = _get_db()
        try:
            return await _run_intelligent_collection_search(
                query, top_k, context_mode, account_id,
                enable_planning, rerank, node_type_filter, db,
            )
        finally:
            db.close()

    @mcp.tool(
        name="search_document",
        description=(
            "Search within ONE specific document by job_id (returned from upload_document or get_collection). "
            "Most precise scope — use when you know exactly which document contains the answer. "
            "context_mode: 'none'=raw chunk, 'narrow'=H3 section, 'deep'=H2 chapter. "
            "node_type_filter: comma-separated like 'table,code'."
        ),
    )
    async def search_document(
        job_id: str,
        query: str,
        top_k: int = 10,
        rerank: bool = False,
        context_mode: str = "none",
        node_type_filter: str | None = None,
    ) -> str:
        from kapsula.core.application.dto.sub_document_search import (
            SubDocumentSearch,
        )
        from kapsula.core.application.dto.single_index_search import (
            SingleIndexSearch,
        )

        db = _get_db()
        try:
            doc = db.query(Document).filter(Document.job_id == job_id).first()
            if not doc:
                return f"Document not found: {job_id}"
            if doc.status != "completed":
                return f"Document not ready. Status: {doc.status}"

            subdocs = (
                db.query(SubDocument).filter(SubDocument.document_id == doc.id).all()
            )

            if subdocs:
                searcher = _get_multi_index_searcher(db)
                results = await searcher.search_subdocuments(
                    SubDocumentSearch(
                        query=query,
                        document_id=doc.id,
                        top_k=min(top_k, 100),
                        rerank=False,
                        context_mode=context_mode,
                        hf_api_token=_hf_token(),
                        node_type_filter=_parse_node_type_filter(node_type_filter),
                    )
                )
            else:
                if not doc.faiss_index_path or not doc.bm25_index_path:
                    return "No search indexes available for this document."
                searcher = _get_multi_index_searcher(db)
                results = await searcher.search_single_index(
                    SingleIndexSearch(
                        query=query,
                        faiss_path=doc.faiss_index_path,
                        bm25_path=doc.bm25_index_path,
                        document_id=doc.id,
                        top_k=min(top_k, 100),
                        rerank=False,
                        context_mode=context_mode,
                        node_type_filter=_parse_node_type_filter(node_type_filter),
                    )
                )

            if not results:
                return "No results found."

            out = [f"Found {len(results)} results in '{doc.filename}' for: {query}\n"]
            for i, r in enumerate(results, 1):
                score = r.get("rerank_score") or r.get("score", 0)
                content = r.get("expanded_content", r.get("content", ""))
                sub_key = r.get("sub_document_key", "")
                src = f" [{sub_key}]" if sub_key else ""
                out.append(f"--- Result {i}{src} score={score:.3f} ---")
                out.append(content[:1500])
                out.append("")
            return "\n".join(out)
        finally:
            db.close()

    @mcp.tool(
        name="intelligent_search_document",
        description=(
            "LLM-powered reasoning within ONE document — plans sub-questions, searches, and synthesizes a grounded answer. "
            "Use when you need to reason about a specific document's content ('summarize this doc', "
            "'what does this doc say about X?'). context_mode: 'none'/'narrow'/'deep'. "
            "enable_planning=True lets the LLM decompose complex questions into sub-searches."
        ),
    )
    async def intelligent_search_document(
        job_id: str,
        query: str,
        top_k: int = 10,
        context_mode: str = "none",
        enable_planning: bool = True,
        rerank: bool = False,
        node_type_filter: str | None = None,
    ) -> str:
        from kapsula.core.application.dto.sub_document_search import (
            SubDocumentSearch,
        )
        from kapsula.core.application.dto.single_index_search import (
            SingleIndexSearch,
        )

        db = _get_db()
        try:
            token = _hf_token()
            if not token:
                return "Error: HF_TOKEN not set."

            def _db_and_plan():
                doc = db.query(Document).filter(Document.job_id == job_id).first()
                if not doc:
                    return None, None, None, "Document not found"
                if doc.status != "completed":
                    return None, None, None, f"Document not ready. Status: {doc.status}"

                document_structure = []
                subdocs = (
                    db.query(SubDocument)
                    .filter(SubDocument.document_id == doc.id)
                    .all()
                )
                if subdocs:
                    for subdoc in subdocs:
                        cards = (
                            db.query(LibraryCard)
                            .filter(
                                LibraryCard.sub_document_id == subdoc.id,
                                LibraryCard.level.in_(["level_1", "level_2", "level_3"]),
                            )
                            .order_by(LibraryCard.level.desc())
                            .limit(20)
                            .all()
                        )
                        if cards:
                            document_structure.append(
                                {
                                    "subdocument_name": subdoc.breadcrumb_key,
                                    "sections": [
                                        {"level": c.level, "title": c.title}
                                        for c in cards
                                    ],
                                }
                            )
                else:
                    cards = (
                        db.query(LibraryCard)
                        .filter(
                            LibraryCard.document_id == doc.id,
                            LibraryCard.level.in_(["level_1", "level_2", "level_3"]),
                        )
                        .order_by(LibraryCard.level.desc())
                        .limit(30)
                        .all()
                    )
                    if cards:
                        document_structure.append(
                            {
                                "subdocument_name": doc.filename,
                                "sections": [
                                    {"level": c.level, "title": c.title} for c in cards
                                ],
                            }
                        )

                search_plan = None
                if enable_planning and document_structure:
                    planner = _get_query_planner()
                    search_plan = planner.plan_document_search(
                        query, document_structure=document_structure
                    )

                return doc, subdocs, document_structure, search_plan

            doc, subdocs, document_structure, search_plan = await asyncio.to_thread(
                _db_and_plan
            )
            if isinstance(search_plan, str):
                return search_plan

            doc_searcher = _get_multi_index_searcher(db)

            async def execute_search(q: str):
                if subdocs:
                    return await doc_searcher.search_subdocuments(
                        SubDocumentSearch(
                            query=q,
                            document_id=doc.id,
                            top_k=min(top_k, 100),
                            rerank=False,
                            context_mode=context_mode,
                            hf_api_token=token,
                        )
                    )
                if not doc.faiss_index_path or not doc.bm25_index_path:
                    return []
                return await doc_searcher.search_single_index(
                    SingleIndexSearch(
                        query=q,
                        faiss_path=doc.faiss_index_path,
                        bm25_path=doc.bm25_index_path,
                        document_id=doc.id,
                        top_k=min(top_k, 100),
                        rerank=False,
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
            plan_info = result.get("plan", {})
            if plan_info:
                parts.append(f"Strategy: {plan_info.get('strategy', '?')}")
                parts.append(f"Sub-questions: {len(plan_info.get('queries', []))}")
                parts.append("")
            parts.append(result.get("answer", "No answer generated."))
            return "\n".join(parts)
        finally:
            db.close()
