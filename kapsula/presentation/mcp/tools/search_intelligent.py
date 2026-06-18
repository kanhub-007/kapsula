"""MCP intelligent search tools — LLM-powered answer synthesis."""

import asyncio

from fastmcp import FastMCP

from kapsula.infrastructure.data import Document, SubDocument

from ._search_helpers import (
    get_topic_card_summary,
    run_intelligent_collection_search,
)
from ._shared import (
    _get_db,
    _get_intelligent_searcher,
    _get_multi_index_searcher,
    _get_query_planner,
    _hf_token,
)


def register_search_intelligent_tools(mcp: FastMCP):
    """Register intelligent search tools: intelligent_search, intelligent_search_document."""

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
        node_type_filter: str | None = None,
    ) -> str:
        db = _get_db()
        try:
            return await run_intelligent_collection_search(
                query,
                top_k,
                context_mode,
                account_id,
                enable_planning,
                node_type_filter,
                db,
            )
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
        node_type_filter: str | None = None,
    ) -> str:
        from kapsula.core.application.dto.single_index_search import (
            SingleIndexSearch,
        )
        from kapsula.core.application.dto.sub_document_search import (
            SubDocumentSearch,
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
                from kapsula.presentation.shared.document_structure_builder import (
                    build_document_structure_from_document,
                    build_document_structure_from_subdocs,
                )

                if subdocs:
                    document_structure = build_document_structure_from_subdocs(
                        subdocs, db
                    )
                else:
                    document_structure = build_document_structure_from_document(
                        document_id=doc.id,
                        fallback_name=doc.filename,
                        db=db,
                        limit=30,
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
                            context_mode=context_mode,
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
            if doc and doc.collection_id:
                topic_summary = get_topic_card_summary(db, doc.collection_id)
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
            return "\n".join(parts)
        finally:
            db.close()
