"""Shared helpers and cached singletons for MCP tools."""

import os
import uuid
import threading
from pathlib import Path

from doc_search.infrastructure.data import (
    SessionLocal,
    Collection,
    Account,
    Document,
)
from doc_search.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

# ── lazy singleton cache ──────────────────────────────────

_cache: dict[str, object] = {}


def _cached(name: str, factory):
    if name not in _cache:
        _cache[name] = factory()
    return _cache[name]


def _clear_cache():
    for obj in _cache.values():
        clear = getattr(obj, "clear_cache", None)
        if callable(clear):
            clear()
    _cache.clear()


def _hf_token():
    return os.getenv("HF_TOKEN") or os.getenv("HF_API_TOKEN")


# ── database ──────────────────────────────────────────────

def _get_db():
    return SessionLocal()


def _resolve_collection(db, collection_id: str) -> Collection | None:
    return (
        db.query(Collection).filter(Collection.collection_id == collection_id).first()
    )


def _resolve_account(db, account_id: str) -> Account | None:
    return db.query(Account).filter(Account.account_id == account_id).first()


# ── cached infrastructure singletons ──────────────────────

def _get_chat_client():
    def _create():
        from doc_search.startup import create_chat_client
        return create_chat_client()
    return _cached("chat_client", _create)


def _get_query_planner():
    def _create():
        from doc_search.startup import create_query_planner
        return create_query_planner(_get_chat_client())
    return _cached("query_planner", _create)


def _get_embedder():
    def _create():
        from doc_search.startup import create_embedder
        return create_embedder()
    return _cached("embedder", _create)


def _get_reranker():
    def _create():
        from doc_search.startup import create_reranker
        return create_reranker()
    return _cached("reranker", _create)


def _get_multi_index_searcher(db):
    from doc_search.startup import create_multi_index_searcher
    return create_multi_index_searcher(
        db_session=db,
        embedder=_get_embedder(),
        reranker=_get_reranker(),
        chat_client=_get_chat_client(),
    )


def _get_intelligent_searcher():
    def _create():
        from doc_search.startup import create_intelligent_searcher
        return create_intelligent_searcher(_get_chat_client())
    return _cached("intelligent_searcher", _create)


def _parse_node_type_filter(node_type_filter: str | None) -> list[str] | None:
    if not node_type_filter:
        return None
    parsed = [item.strip() for item in node_type_filter.split(",") if item.strip()]
    return parsed or None


# ── upload helper ─────────────────────────────────────────

def _upload_markdown_file(
    file_path: str,
    collection_id: str,
    max_tokens: int = 512,
    ingestion_mode: str = "indexed",
) -> str:
    """Upload a markdown file to a collection. Shared by API and MCP tools."""
    from doc_search.core.application.dto.upload_ingestion_mode import (
        UploadIngestionMode,
    )

    try:
        ingestion_mode = UploadIngestionMode.normalize(ingestion_mode)
    except ValueError as exc:
        return f"Error: {exc}"

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
            job_id=job_id,
            collection_id=col.id,
            filename=p.name,
            size=len(content.encode("utf-8")),
            ip_address="127.0.0.1",
            content=content,
            status="processing",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        from doc_search.presentation.api.tasks import (
            process_document_with_subdocuments,
            processing_status,
        )

        processing_status[job_id] = {
            "status": "processing",
            "progress": 0,
            "stage": "queued",
            "message": f"Document queued for {ingestion_mode} ingestion...",
            "ingestion_mode": ingestion_mode,
        }
        from doc_search.presentation.upload.upload_job_manager import (
            UploadJobManager,
        )

        UploadJobManager().create(
            job_id,
            filename=p.name,
            collection_id=col.id,
            collection_name=col.name,
            ingestion_mode=ingestion_mode,
        )

        threading.Thread(
            target=process_document_with_subdocuments,
            args=(job_id, content, max_tokens, SessionLocal(), ingestion_mode),
            daemon=True,
        ).start()

        return (
            f"Uploaded: {p.name}\n"
            f"  Collection: {col.name}\n"
            f"  job_id: {job_id}\n"
            f"  Status: processing\n"
            f"  Ingestion mode: {ingestion_mode}"
        )
    finally:
        db.close()
