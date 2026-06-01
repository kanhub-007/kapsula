"""MCP tools — doc-search operations exposed to MCP clients."""

import asyncio
import json
import os
import threading
import uuid
from pathlib import Path

from fastmcp import FastMCP

from doc_search.infrastructure.data import (
    SessionLocal, Collection, Document, Account, LibraryCard,
    SubDocument, DocumentStructure, Chunk,
)
from doc_search.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

# ── lazy singleton cache for expensive objects ──────────────────
# These are created once at first use and reused across all MCP tool calls.
# This avoids creating new embedder/reranker/chat-client instances per request,
# which would load models from disk and initialize HTTP clients repeatedly.

_cache: dict[str, object] = {}


def _cached(name: str, factory):
    """Get or create a cached singleton. Thread-safe enough for MCP usage."""
    if name not in _cache:
        _cache[name] = factory()
    return _cache[name]


def _get_db():
    return SessionLocal()


def _hf_token():
    return os.getenv("HF_TOKEN") or os.getenv("HF_API_TOKEN")


def _resolve_collection(db, collection_id: str) -> Collection | None:
    return db.query(Collection).filter(Collection.collection_id == collection_id).first()


def _resolve_account(db, account_id: str) -> Account | None:
    return db.query(Account).filter(Account.account_id == account_id).first()


def _get_chat_client():
    """Return a cached HuggingFaceChatClient singleton."""
    def _create():
        from doc_search.startup import create_chat_client
        return create_chat_client()
    return _cached("chat_client", _create)


def _get_query_planner():
    """Return a cached QueryPlanner singleton."""
    def _create():
        from doc_search.startup import create_query_planner
        return create_query_planner(_get_chat_client())
    return _cached("query_planner", _create)


def _get_embedder():
    """Return a cached HuggingFaceEmbedder singleton (stateless HTTP client)."""
    def _create():
        from doc_search.startup import create_embedder
        return create_embedder()
    return _cached("embedder", _create)


def _get_reranker():
    """Return a cached LocalCrossEncoderReranker singleton (lazy-loads model)."""
    def _create():
        from doc_search.startup import create_reranker
        return create_reranker()
    return _cached("reranker", _create)


def _get_multi_index_searcher(db):
    """Return a MultiIndexSearcher with cached embedder/reranker/chat_client.

    The MultiIndexSearcher itself is NOT cached (depends on db session
    for SqlSearchDataAccess), but all its expensive dependencies are.
    """
    from doc_search.startup import create_multi_index_searcher
    return create_multi_index_searcher(
        db_session=db,
        embedder=_get_embedder(),
        reranker=_get_reranker(),
        chat_client=_get_chat_client(),
    )


def _get_intelligent_searcher():
    """Return a cached IntelligentSearcher singleton."""
    def _create():
        from doc_search.startup import create_intelligent_searcher
        return create_intelligent_searcher(_get_chat_client())
    return _cached("intelligent_searcher", _create)


def _clear_cache():
    """Clear the singleton cache (used in tests)."""
    _cache.clear()


# ── reused intelligent‑search helper ──────────────────────────

async def _run_intelligent_collection_search(
    query: str, top_k: int, context_mode: str, account_id: str | None,
    enable_planning: bool, rerank: bool, node_type_filter: str | None, db,
) -> str:
    from doc_search.core.application.dto.collection_search import CollectionSearch
    from doc_search.core.application.use_cases.selectors.collection_selector import CollectionSelector

    token = _hf_token()
    if not token:
        return "Error: HF_TOKEN not set."

    # Offload sync DB queries to a thread to avoid blocking the event loop
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
            card = db.query(LibraryCard).filter(
                LibraryCard.collection_id == c.id, LibraryCard.level == "collection",
            ).first()
            meta.append({
                "id": c.id, "name": c.name,
                "library_card_summary": card.content[:500] if card else c.name,
                "document_count": len(c.documents),
            })

        # Route to the best collection (sync LLM call — offloaded to thread)
        routed_ids = router.select(query, meta)
        routed_id = routed_ids[0] if routed_ids else collections[0].id
        routed_coll = db.query(Collection).filter(Collection.id == routed_id).first()

        # Build document structure for planning
        document_structure = []
        if routed_coll:
            for doc in routed_coll.documents:
                for subdoc in doc.sub_documents:
                    cards = db.query(LibraryCard).filter(
                        LibraryCard.sub_document_id == subdoc.id,
                        LibraryCard.level.in_(["level_1", "level_2", "level_3"]),
                    ).order_by(LibraryCard.level.desc()).limit(20).all()
                    if cards:
                        document_structure.append({
                            "subdocument_name": subdoc.breadcrumb_key,
                            "sections": [{"level": c.level, "title": c.title} for c in cards],
                        })

        # Plan sub-questions (sync LLM call — offloaded to thread)
        search_plan = None
        if enable_planning and document_structure:
            planner = _get_query_planner()
            search_plan = planner.plan_document_search(query, document_structure=document_structure)

        return collections, routed_coll, document_structure, search_plan

    result_tuple = await asyncio.to_thread(_db_work)
    if result_tuple[0] is None:
        return "No collections found."
    collections, routed_coll, document_structure, search_plan = result_tuple

    # Now run the async search + evaluation (these are properly async)
    coll_searcher = _get_multi_index_searcher(db)

    async def execute_search(q: str):
        return await coll_searcher.search_collections(
            CollectionSearch(
                query=q, account_id=account_id or "",
                top_k=min(top_k, 100), rerank=rerank,
                context_mode=context_mode, hf_api_token=token,
            )
        )

    engine = _get_intelligent_searcher()
    result = await engine.evaluate_and_answer_with_planning(
        query=query, search_function=execute_search,
        max_context_length=8000, plan=search_plan,
    )

    parts = []
    plan_info = result.get("plan", {})
    if plan_info:
        parts.append(f"Strategy: {plan_info.get('strategy', '?')}")
        parts.append(f"Sub-questions: {len(plan_info.get('queries', []))}")
        parts.append("")
    parts.append(result.get("answer", "No answer generated."))
    return "\n".join(parts)


# ── tool registration ─────────────────────────────────────────

def register_tools(mcp: FastMCP):
    """Register all doc-search tools on the given MCP server instance."""

    # ═══════════════════════════════════════════════════════════
    #  ACCOUNTS
    # ═══════════════════════════════════════════════════════════

    @mcp.tool(
        name="create_account",
        description="Create a new account (tenant). Returns the account GUID.",
    )
    def create_account(name: str) -> str:
        db = _get_db()
        try:
            account_id = str(uuid.uuid4())
            acc = Account(account_id=account_id, name=name, ip_address="127.0.0.1")
            db.add(acc)
            db.commit()
            return f"Account created: {name}\n  account_id: {account_id}"
        finally:
            db.close()

    @mcp.tool(
        name="list_accounts",
        description="List all accounts with collection counts.",
    )
    def list_accounts() -> str:
        db = _get_db()
        try:
            accounts = db.query(Account).order_by(Account.created_at.desc()).all()
            if not accounts:
                return "No accounts found."
            lines = [f"Accounts ({len(accounts)}):\n"]
            for a in accounts:
                lines.append(f"  • {a.name} — {len(a.collections)} collections — {a.account_id}")
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="get_account",
        description="Get account details including all collections and document counts.",
    )
    def get_account(account_id: str) -> str:
        db = _get_db()
        try:
            acc = _resolve_account(db, account_id)
            if not acc:
                return f"Account not found: {account_id}"
            lines = [
                f"Account: {acc.name}",
                f"account_id: {acc.account_id}",
                f"Created: {acc.created_at.isoformat() if acc.created_at else '?'}",
                f"Collections: {len(acc.collections)}",
            ]
            for col in acc.collections:
                lines.append(f"  • {col.name} ({len(col.documents)} docs) — {col.collection_id}")
            return "\n".join(lines)
        finally:
            db.close()

    # ═══════════════════════════════════════════════════════════
    #  COLLECTIONS
    # ═══════════════════════════════════════════════════════════

    @mcp.tool(
        name="create_collection",
        description="Create a new collection within an account. Returns the collection GUID.",
    )
    def create_collection(name: str, account_id: str | None = None) -> str:
        db = _get_db()
        try:
            acc = None
            if account_id:
                acc = _resolve_account(db, account_id)
                if not acc:
                    return f"Account not found: {account_id}"

            collection_id = str(uuid.uuid4())
            col = Collection(
                collection_id=collection_id, name=name,
                account_id=acc.id if acc else None,
                ip_address="127.0.0.1",
            )
            db.add(col)
            db.commit()
            extra = f" (account: {acc.name})" if acc else " (no account)"
            return f"Collection created: {name}{extra}\n  collection_id: {collection_id}"
        finally:
            db.close()

    @mcp.tool(
        name="get_collection",
        description="Get collection details including document list and library card summary.",
    )
    def get_collection(collection_id: str) -> str:
        db = _get_db()
        try:
            col = _resolve_collection(db, collection_id)
            if not col:
                return f"Collection not found: {collection_id}"

            card = db.query(LibraryCard).filter(
                LibraryCard.collection_id == col.id, LibraryCard.level == "collection",
            ).first()

            lines = [
                f"Collection: {col.name}",
                f"collection_id: {col.collection_id}",
                f"Documents: {len(col.documents)}",
                f"Created: {col.created_at.isoformat() if col.created_at else '?'}",
            ]
            if col.account:
                lines.append(f"Account: {col.account.name} ({col.account.account_id})")
            if card:
                lines.append(f"\nSummary: {card.content[:300]}")
            if col.documents:
                lines.append(f"\nDocuments:")
                for d in col.documents:
                    lines.append(f"  • {d.filename} [{d.status}] — {len(d.chunks)} chunks — job_id={d.job_id}")
            return "\n".join(lines)
        finally:
            db.close()

    # ═══════════════════════════════════════════════════════════
    #  DOCUMENTS
    # ═══════════════════════════════════════════════════════════

    @mcp.tool(
        name="upload_document",
        description="Upload a markdown (.md) file to a collection. Returns a job_id for progress tracking.",
    )
    def upload_document(file_path: str, collection_id: str, max_tokens: int = 512) -> str:
        p = Path(file_path)
        if not p.exists():
            return f"Error: file not found — {file_path}"
        if p.suffix.lower() != ".md":
            return f"Error: only .md files accepted — got {p.suffix}"

        db = _get_db()
        try:
            col = _resolve_collection(db, collection_id)
            if not col:
                return f"Error: collection not found — {collection_id}"

            content = p.read_text(encoding="utf-8")
            job_id = str(uuid.uuid4())

            doc = Document(
                job_id=job_id, collection_id=col.id, filename=p.name,
                size=len(content.encode("utf-8")), ip_address="127.0.0.1",
                content=content, status="processing",
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)

            from doc_search.presentation.api.tasks import process_document_with_subdocuments
            threading.Thread(
                target=process_document_with_subdocuments,
                args=(job_id, content, max_tokens, SessionLocal()),
                daemon=True,
            ).start()

            return (
                f"Uploaded: {p.name}\n"
                f"  Collection: {col.name}\n"
                f"  job_id: {job_id}\n"
                f"  Status: processing"
            )
        finally:
            db.close()

    @mcp.tool(
        name="list_documents",
        description="List uploaded documents with status and chunk counts. Optionally filter by collection.",
    )
    def list_documents(collection_id: str | None = None) -> str:
        db = _get_db()
        try:
            q = db.query(Document)
            if collection_id:
                col = _resolve_collection(db, collection_id)
                if not col:
                    return f"Collection not found: {collection_id}"
                q = q.filter(Document.collection_id == col.id)
            docs = q.order_by(Document.created_at.desc()).all()
            if not docs:
                return "No documents found."

            lines = [f"Documents ({len(docs)}):\n"]
            for d in docs:
                cn = d.collection.name if d.collection else "?"
                lines.append(f"  • {d.filename} [{d.status}] — {len(d.chunks)} chunks, {cn}")
                lines.append(f"    job_id: {d.job_id}")
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="get_document_info",
        description="Get document details: status, structure skeleton, and chunk previews.",
    )
    def get_document_info(job_id: str) -> str:
        db = _get_db()
        try:
            doc = db.query(Document).filter(Document.job_id == job_id).first()
            if not doc:
                return f"Document not found: {job_id}"

            structure = db.query(DocumentStructure).filter(
                DocumentStructure.document_id == doc.id,
            ).first()
            chunks = db.query(Chunk).filter(
                Chunk.document_id == doc.id,
            ).order_by(Chunk.chunk_index).all()

            lines = [
                f"Document: {doc.filename}",
                f"Status: {doc.status}",
                f"Collection: {doc.collection.name if doc.collection else '?'}",
                f"Size: {doc.size} bytes",
                f"Chunks: {len(chunks)}",
                f"Duration: {doc.duration:.2f}s" if doc.duration else "Duration: —",
                f"Created: {doc.created_at.isoformat() if doc.created_at else '?'}",
                f"job_id: {doc.job_id}",
            ]
            if structure and structure.skeleton_structure:
                lines.append("\n--- Structure (first 1000 chars) ---")
                lines.append(structure.skeleton_structure[:1000])
            if chunks:
                lines.append("\n--- First 3 Chunks ---")
                for ch in chunks[:3]:
                    preview = ch.content[:300].replace("\n", " ")
                    lines.append(f"  [{ch.chunk_index}] ({ch.token_count} tokens): {preview}...")
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="get_document_progress",
        description="Check the real-time processing progress of an uploaded document.",
    )
    def get_document_progress(job_id: str) -> str:
        db = _get_db()
        try:
            doc = db.query(Document).filter(Document.job_id == job_id).first()
            if not doc:
                return f"Document not found: {job_id}"

            from doc_search.presentation.api.tasks import get_processing_status
            status = get_processing_status(job_id)

            if status:
                return (
                    f"Document: {doc.filename}\n"
                    f"Status: {status.get('status', '?')}\n"
                    f"Progress: {status.get('progress', 0)}%\n"
                    f"Stage: {status.get('stage', '?')}\n"
                    f"Message: {status.get('message', '')}\n"
                    f"Chunks: {status.get('chunk_count', '—')}\n"
                    f"Duration: {status.get('duration', '—')}"
                )
            return f"Document: {doc.filename}\nStatus: {doc.status} (no live progress)"
        finally:
            db.close()

    @mcp.tool(
        name="download_document_chunks",
        description="Export all chunks of a document as formatted text with chunk indices and metadata.",
    )
    def download_document_chunks(job_id: str) -> str:
        db = _get_db()
        try:
            doc = db.query(Document).filter(Document.job_id == job_id).first()
            if not doc:
                return f"Document not found: {job_id}"
            if doc.status != "completed":
                return f"Document not ready. Status: {doc.status}"

            chunks = db.query(Chunk).filter(
                Chunk.document_id == doc.id,
            ).order_by(Chunk.chunk_index).all()

            lines = [
                f"Document: {doc.filename}",
                f"Total chunks: {len(chunks)}",
                f"job_id: {doc.job_id}",
                "",
            ]
            for ch in chunks:
                meta = {}
                if ch.chunk_metadata:
                    try:
                        meta = json.loads(ch.chunk_metadata)
                    except json.JSONDecodeError:
                        pass
                header = meta.get("header", "")
                node_type = meta.get("node_type", "text")
                lines.append(f"--- Chunk {ch.chunk_index} [{node_type}] ({ch.token_count} tokens) ---")
                if header:
                    lines.append(f"  Header: {header}")
                lines.append(ch.content[:2000])
                lines.append("")
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="download_document_structure",
        description="Export the heading skeleton of a document as markdown.",
    )
    def download_document_structure(job_id: str) -> str:
        db = _get_db()
        try:
            doc = db.query(Document).filter(Document.job_id == job_id).first()
            if not doc:
                return f"Document not found: {job_id}"
            if doc.status != "completed":
                return f"Document not ready. Status: {doc.status}"

            structure = db.query(DocumentStructure).filter(
                DocumentStructure.document_id == doc.id,
            ).first()
            if not structure or not structure.skeleton_structure:
                return "No structure available."

            return (
                f"# Structure: {doc.filename}\n"
                f"# job_id: {doc.job_id}\n\n"
                f"{structure.skeleton_structure}"
            )
        finally:
            db.close()

    # ═══════════════════════════════════════════════════════════
    #  SEARCH
    # ═══════════════════════════════════════════════════════════

    @mcp.tool(
        name="search_documents",
        description="Hybrid search (FAISS + BM25) across all collections. Returns chunks with scores and source info.",
    )
    async def search_documents(
        query: str,
        top_k: int = 10,
        rerank: bool = False,
        context_mode: str = "none",
        account_id: str | None = None,
        node_type_filter: str | None = None,
    ) -> str:
        from doc_search.core.application.dto.collection_search import CollectionSearch

        db = _get_db()
        try:
            searcher = _get_multi_index_searcher(db)
            results = await searcher.search_collections(
                CollectionSearch(
                    query=query, account_id=account_id or "",
                    top_k=min(top_k, 100), rerank=rerank,
                    context_mode=context_mode, hf_api_token=_hf_token(),
                )
            )
            if not results:
                return "No results found."
            out = [f"Found {len(results)} results for: {query}\n"]
            for i, r in enumerate(results, 1):
                src = r.get("collection_name", "?")
                doc = r.get("document_filename", "?")
                score = r.get("rerank_score") or r.get("score", 0)
                content = r.get("expanded_content", r.get("content", ""))
                out.append(f"--- Result {i} [{src}/{doc}] score={score:.3f} ---")
                out.append(content[:1500])
                out.append("")
            return "\n".join(out)
        finally:
            db.close()

    @mcp.tool(
        name="search_document",
        description="Hybrid search within a single document by job_id. Use for targeted searches in a specific doc.",
    )
    async def search_document(
        job_id: str,
        query: str,
        top_k: int = 10,
        rerank: bool = False,
        context_mode: str = "none",
        node_type_filter: str | None = None,
    ) -> str:
        from doc_search.core.application.dto.sub_document_search import SubDocumentSearch
        from doc_search.core.application.dto.single_index_search import SingleIndexSearch

        db = _get_db()
        try:
            doc = db.query(Document).filter(Document.job_id == job_id).first()
            if not doc:
                return f"Document not found: {job_id}"
            if doc.status != "completed":
                return f"Document not ready. Status: {doc.status}"

            subdocs = db.query(SubDocument).filter(SubDocument.document_id == doc.id).all()

            if subdocs:
                searcher = _get_multi_index_searcher(db)
                results = await searcher.search_subdocuments(
                    SubDocumentSearch(
                        query=query, document_id=doc.id,
                        top_k=min(top_k, 100), rerank=rerank,
                        context_mode=context_mode, hf_api_token=_hf_token(),
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
                        rerank=rerank,
                        context_mode=context_mode,
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
        name="intelligent_search",
        description="LLM-powered search across collections: plans sub-questions, searches, generates a grounded answer.",
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
                query, top_k, context_mode, account_id, enable_planning, rerank, node_type_filter, db,
            )
        finally:
            db.close()

    @mcp.tool(
        name="intelligent_search_document",
        description="LLM-powered search within a single document: plans, searches, and generates a grounded answer.",
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
        from doc_search.core.application.dto.sub_document_search import SubDocumentSearch
        from doc_search.core.application.dto.single_index_search import SingleIndexSearch

        db = _get_db()
        try:
            token = _hf_token()
            if not token:
                return "Error: HF_TOKEN not set."

            # Offload sync DB + planning work to thread pool
            def _db_and_plan():
                doc = db.query(Document).filter(Document.job_id == job_id).first()
                if not doc:
                    return None, None, None, "Document not found"
                if doc.status != "completed":
                    return None, None, None, f"Document not ready. Status: {doc.status}"

                document_structure = []
                subdocs = db.query(SubDocument).filter(SubDocument.document_id == doc.id).all()
                if subdocs:
                    for subdoc in subdocs:
                        cards = db.query(LibraryCard).filter(
                            LibraryCard.sub_document_id == subdoc.id,
                            LibraryCard.level.in_(["level_1", "level_2", "level_3"]),
                        ).order_by(LibraryCard.level.desc()).limit(20).all()
                        if cards:
                            document_structure.append({
                                "subdocument_name": subdoc.breadcrumb_key,
                                "sections": [{"level": c.level, "title": c.title} for c in cards],
                            })
                else:
                    cards = db.query(LibraryCard).filter(
                        LibraryCard.document_id == doc.id,
                        LibraryCard.level.in_(["level_1", "level_2", "level_3"]),
                    ).order_by(LibraryCard.level.desc()).limit(30).all()
                    if cards:
                        document_structure.append({
                            "subdocument_name": doc.filename,
                            "sections": [{"level": c.level, "title": c.title} for c in cards],
                        })

                search_plan = None
                if enable_planning and document_structure:
                    planner = _get_query_planner()
                    search_plan = planner.plan_document_search(query, document_structure=document_structure)

                return doc, subdocs, document_structure, search_plan

            doc, subdocs, document_structure, search_plan = await asyncio.to_thread(_db_and_plan)
            if isinstance(search_plan, str):  # error message returned
                return search_plan

            doc_searcher = _get_multi_index_searcher(db)

            async def execute_search(q: str):
                if subdocs:
                    return await doc_searcher.search_subdocuments(
                        SubDocumentSearch(
                            query=q, document_id=doc.id,
                            top_k=min(top_k, 100), rerank=rerank,
                            context_mode=context_mode, hf_api_token=token,
                        )
                    )
                if not doc.faiss_index_path or not doc.bm25_index_path:
                    return []
                return await doc_searcher.search_single_index(
                    SingleIndexSearch(
                        query=q, faiss_path=doc.faiss_index_path,
                        bm25_path=doc.bm25_index_path, document_id=doc.id,
                        top_k=min(top_k, 100), rerank=rerank,
                        context_mode=context_mode,
                    )
                )

            engine = _get_intelligent_searcher()
            result = await engine.evaluate_and_answer_with_planning(
                query=query, search_function=execute_search,
                max_context_length=8000, plan=search_plan,
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

    # ═══════════════════════════════════════════════════════════
    #  EXPORT
    # ═══════════════════════════════════════════════════════════

    @mcp.tool(
        name="export_account",
        description="Export complete account data: all collections, documents, and library cards.",
    )
    def export_account(account_id: str) -> str:
        db = _get_db()
        try:
            acc = _resolve_account(db, account_id)
            if not acc:
                return f"Account not found: {account_id}"

            lines = [
                f"# Account: {acc.name}",
                f"account_id: {acc.account_id}",
                f"Created: {acc.created_at.isoformat() if acc.created_at else '?'}",
                f"Collections: {len(acc.collections)}",
                "",
            ]
            for col in acc.collections:
                lines.append(f"## Collection: {col.name} ({col.collection_id})")
                lines.append(f"  Documents: {len(col.documents)}")
                for doc in col.documents:
                    chunks = len(doc.chunks) if doc.chunks else 0
                    cards = db.query(LibraryCard).filter(
                        LibraryCard.document_id == doc.id,
                        LibraryCard.collection_id == None,
                    ).count()
                    lines.append(f"  - {doc.filename} [{doc.status}] — {chunks} chunks, {cards} library cards — job_id={doc.job_id}")
                # collection-level library cards
                col_cards = db.query(LibraryCard).filter(
                    LibraryCard.collection_id == col.id, LibraryCard.document_id == None,
                ).all()
                if col_cards:
                    lines.append(f"  Collection-level cards: {len(col_cards)}")
                    for cc in col_cards[:3]:
                        lines.append(f"    [{cc.level}] {cc.title}: {cc.content[:200]}...")
                lines.append("")
            return "\n".join(lines)
        finally:
            db.close()

    @mcp.tool(
        name="export_collection",
        description="Export complete collection data: all documents and library cards.",
    )
    def export_collection(collection_id: str) -> str:
        db = _get_db()
        try:
            col = _resolve_collection(db, collection_id)
            if not col:
                return f"Collection not found: {collection_id}"

            lines = [
                f"# Collection: {col.name}",
                f"collection_id: {col.collection_id}",
                f"Documents: {len(col.documents)}",
                f"Created: {col.created_at.isoformat() if col.created_at else '?'}",
                "",
            ]
            for doc in col.documents:
                chunks = len(doc.chunks) if doc.chunks else 0
                cards = db.query(LibraryCard).filter(
                    LibraryCard.document_id == doc.id,
                    LibraryCard.collection_id == None,
                ).all()
                lines.append(f"## Document: {doc.filename}")
                lines.append(f"  Status: {doc.status}  |  Size: {doc.size} bytes  |  Chunks: {chunks}")
                lines.append(f"  job_id: {doc.job_id}")
                if cards:
                    lines.append(f"  Library cards ({len(cards)}):")
                    for c in cards[:5]:
                        lines.append(f"    [{c.level}] {c.title}: {c.content[:150]}...")
                lines.append("")

            col_cards = db.query(LibraryCard).filter(
                LibraryCard.collection_id == col.id, LibraryCard.document_id == None,
            ).all()
            if col_cards:
                lines.append("## Collection-level Library Cards")
                for cc in col_cards:
                    lines.append(f"  [{cc.level}] {cc.title}: {cc.content[:300]}...")
                lines.append("")
            return "\n".join(lines)
        finally:
            db.close()

    # ═══════════════════════════════════════════════════════════
    #  LIST COLLECTIONS
    # ═══════════════════════════════════════════════════════════

    @mcp.tool(
        name="list_collections",
        description="List all document collections with document counts and summaries.",
    )
    def list_collections(account_id: str | None = None) -> str:
        db = _get_db()
        try:
            q = db.query(Collection)
            if account_id:
                q = q.join(Account).filter(Account.account_id == account_id)
            collections = q.order_by(Collection.created_at.desc()).all()
            if not collections:
                return "No collections found."
            lines = [f"Collections ({len(collections)}):\n"]
            for c in collections:
                card = db.query(LibraryCard).filter(
                    LibraryCard.collection_id == c.id, LibraryCard.level == "collection",
                ).first()
                summary = card.content[:120] if card else "No summary"
                lines.append(f"  • {c.name} ({len(c.documents)} docs) — {c.collection_id}")
                lines.append(f"    {summary}")
            return "\n".join(lines)
        finally:
            db.close()

    logger.info("Registered 18 MCP tools")
