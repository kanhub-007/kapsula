"""MCP document search tools — raw chunk retrieval."""

import asyncio

from fastmcp import FastMCP

from kapsula.infrastructure.data import Document, SubDocument

from ._shared import (
    _get_db,
    _hf_token,
    _parse_node_type_filter,
    _get_multi_index_searcher,
    _get_search_job_manager,
)
from ._search_helpers import (
    run_search_documents_text,
    log_search_miss,
)


def register_search_document_tools(mcp: FastMCP):
    """Register document-level search tools: search_documents, search_collection, search_document."""

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
        context_mode: str = "none",
        account_id: str | None = None,
        node_type_filter: str | None = None,
        routing_mode: str = "auto",
    ) -> str:
        return await run_search_documents_text(
            query=query,
            top_k=top_k,
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
        context_mode: str = "none",
        node_type_filter: str | None = None,
        routing_mode: str = "auto",
    ) -> str:
        return await run_search_documents_text(
            query=query,
            top_k=top_k,
            context_mode=context_mode,
            collection_id=collection_id,
            node_type_filter=node_type_filter,
            routing_mode=routing_mode,
        )

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
