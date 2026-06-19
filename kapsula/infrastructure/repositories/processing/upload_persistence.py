"""Upload pipeline persistence helpers.

Extracted from ``presentation/api/tasks.py`` so the pipeline (application
layer) can call them without importing presentation. Each helper is one
bounded phase of chunk/card persistence. The pipeline's ``_chunk_and_persist``
step orchestrates them.

These still touch the ORM directly (CQRS-lite write exception is not yet
applied to chunk writes — tracked separately). They live in infrastructure
because they perform DB I/O.
"""

import json
import re
import time

from sqlalchemy.orm import Session

from kapsula.infrastructure.data import (
    Chunk,
    Document,
    LibraryCard,
    SubDocument,
    SubDocumentPage,
)
from kapsula.infrastructure.logging_config import get_logger
from kapsula.infrastructure.repositories.chunking.breadcrumb_parser import (
    generate_content_hash,
)
from kapsula.infrastructure.repositories.chunking.header_matcher import (
    match_header_to_parents,
)

logger = get_logger(__name__)

_IMG_MD_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_FIG_LABEL_RE = re.compile(r"^\s*fig(?:ure)?\s*\d*[:.]?\s*", re.IGNORECASE)


def strip_section_images(content: str) -> str:
    """Remove image markdown and leading Figure labels from section content."""
    if not content:
        return content
    cleaned = _IMG_MD_RE.sub("", content)
    cleaned = _FIG_LABEL_RE.sub("", cleaned, count=1)
    return cleaned.lstrip()


def load_document_by_job_id(db: Session, job_id: str):
    """Return the ORM Document for *job_id*, or raise ValueError."""
    from kapsula.infrastructure.data import Document

    document = db.query(Document).filter(Document.job_id == job_id).first()
    if not document:
        raise ValueError(f"Document with job_id {job_id} not found")
    return document


def mark_document_failed(
    db: Session,
    job_id: str,
    message: str,
    progress_store: dict,
    job_manager,
) -> None:
    """Mark the document failed in DB, live progress, and the job table."""
    from kapsula.infrastructure.data import Document

    logger.exception(message)
    document = db.query(Document).filter(Document.job_id == job_id).first()
    if document:
        document.status = "failed"
        db.commit()
    progress_store[job_id] = {
        "status": "failed",
        "progress": 0,
        "stage": "failed",
        "message": message,
    }
    job_manager.update(
        job_id,
        status="failed",
        progress=0,
        stage="failed",
        error=message,
    )


def persist_flat_chunks(
    db: Session,
    document: Document,
    chunks_with_citations: list[dict],
    parent_sections: dict,
) -> None:
    """Persist chunks + parent-section cards for the flat path, then link."""
    _persist_chunks(db, document.id, chunks_with_citations)
    _persist_parent_cards(db, document, parent_sections)


def mark_deferred_maintenance(ctx, *, summary: bool) -> None:
    """Mark the collection stale + increment uploads for deferred maintenance.

    Called by Fast/Indexed strategies' ``rebuild_aggregates`` so the old
    mark-stale-when-skipping behaviour is preserved (spec S3.2).
    """
    ctx.maintenance_state.mark_collection_stale(
        ctx.document.collection,
        summary=summary,
        collection_index=True,
        account_index=True,
    )
    if ctx.document.collection:
        ctx.maintenance_state.increment_uploads(ctx.document.collection.collection_id)


def build_indexes_for_context(ctx) -> None:
    """Build FAISS + BM25 indexes, branching on flat vs sub-document.

    Reads ``ctx.subdoc_plan``: when present, builds per-sub-document indexes
    via :class:`SubDocumentBatchIndexer`; otherwise builds a single
    document-level index. Shared by the Indexed and Full strategies so both
    modes handle Russian-Doll documents identically.
    """
    if ctx.subdoc_plan:
        _build_subdocument_indexes(ctx)
    else:
        from kapsula.infrastructure.repositories.processing._chunk_linker import (
            _build_document_indexes,
        )

        _build_document_indexes(
            ctx.job_id,
            ctx.document,
            ctx.chunks,
            ctx.db,
            ctx.ingestion_mode,
            ctx.progress,
            embedder=ctx.embedder,
        )


def _build_subdocument_indexes(ctx) -> None:
    """Batch-embed and build per-sub-document indexes."""
    from kapsula.infrastructure.data import SubDocument as OrmSubDocument
    from kapsula.infrastructure.data.connection import DATA_DIR
    from kapsula.infrastructure.repositories.indexing import DocumentIndexBuilder
    from kapsula.infrastructure.repositories.processing.sub_document_batch_indexer import (
        SubDocumentBatchIndexer,
    )

    builder = DocumentIndexBuilder(ctx.embedder, DATA_DIR)
    key_to_id = {
        sd.breadcrumb_key: sd.id
        for sd in ctx.db.query(OrmSubDocument)
        .filter(OrmSubDocument.document_id == ctx.document.id)
        .all()
    }
    pending = [
        {
            "subdoc_id": key_to_id.get(entry["breadcrumb_key"]),
            "breadcrumb_key": entry["breadcrumb_key"],
            "chunks": entry["chunks"],
        }
        for entry in ctx.subdoc_plan
    ]
    SubDocumentBatchIndexer(builder, ctx.progress).build(
        db=ctx.db,
        document=ctx.document,
        pending_subdocument_indexes=[i for i in pending if i["subdoc_id"] is not None],
        job_id=ctx.job_id,
        upload_start_time=ctx.start_time,
        ingestion_mode=ctx.ingestion_mode,
    )


def persist_subdocuments(
    db: Session,
    document: Document,
    subdoc_plan: list[dict],
) -> int:
    """Create SubDocument rows + pages + chunks + cards for each plan entry.

    Returns the total chunk count persisted.
    """
    total = 0
    for entry in subdoc_plan:
        breadcrumb_key = entry["breadcrumb_key"]
        pages = entry["pages"]
        chunks = entry["chunks"]
        parent_sections = entry["parent_sections"]

        subdoc = SubDocument(
            document_id=document.id,
            breadcrumb_key=breadcrumb_key,
            breadcrumb_level=2,
            page_count=len(pages),
        )
        db.add(subdoc)
        db.flush()

        for page in pages:
            db.add(
                SubDocumentPage(
                    sub_document_id=subdoc.id,
                    page_title=page["title"],
                    breadcrumb_full=page["breadcrumb"],
                    content_hash=generate_content_hash(page["content"]),
                )
            )

        _link_and_persist_subdoc_chunks(db, document, subdoc, chunks, parent_sections)
        _persist_subdoc_cards(
            db, document, subdoc, breadcrumb_key, pages, parent_sections
        )
        # Citation resolution mutates Chunk rows already added in this
        # session; a single flush exposes their ids to the resolver, then one
        # commit per subdocument persists the whole subdoc atomically (closes
        # M10: previously two commits per subdoc = 2N fsyncs on a large upload).
        db.flush()
        _resolve_subdoc_citations(db, subdoc.id)
        db.commit()
        total += len(chunks)
    return total


# ── internals ────────────────────────────────────────────────────────


def _persist_chunks(db: Session, document_id: int, chunks: list[dict]) -> None:
    for chunk_data in chunks:
        db.add(
            Chunk(
                document_id=document_id,
                content=chunk_data["content"],
                chunk_index=chunk_data["metadata"]["chunk_index"],
                token_count=chunk_data["token_count"],
                chunk_metadata=json.dumps(chunk_data["metadata"]),
            )
        )
    db.commit()


def _persist_parent_cards(
    db: Session, document: Document, parent_sections: dict
) -> None:
    for doc_id, section_data in parent_sections.items():
        db.add(
            LibraryCard(
                collection_id=document.collection_id,
                document_id=document.id,
                doc_id=doc_id,
                level=section_data["level"],
                title=section_data["title"],
                content=section_data["content"],
                extra_metadata=json.dumps(
                    {
                        "extraction_time": time.time(),
                        "start_char": section_data.get("start_char", 0),
                        "end_char": section_data.get("end_char", 0),
                    }
                ),
            )
        )
    db.commit()


def _link_and_persist_subdoc_chunks(
    db: Session,
    document: Document,
    subdoc: SubDocument,
    chunks: list[dict],
    parent_sections: dict,
) -> dict:
    stats = {
        "with_immediate": 0,
        "with_chapter": 0,
        "with_page": 0,
        "no_match": 0,
    }
    for chunk_data in chunks:
        header = chunk_data["metadata"].get("header", "")
        parents = match_header_to_parents(header, parent_sections)
        chunk_data["metadata"]["parents"] = parents
        if parents.get("immediate"):
            stats["with_immediate"] += 1
        if parents.get("chapter"):
            stats["with_chapter"] += 1
        if parents.get("page"):
            stats["with_page"] += 1
        if not any(parents.values()):
            stats["no_match"] += 1
        db.add(
            Chunk(
                document_id=document.id,
                sub_document_id=subdoc.id,
                content=chunk_data["content"],
                chunk_index=chunk_data["metadata"]["chunk_index"],
                token_count=chunk_data["token_count"],
                chunk_metadata=json.dumps(chunk_data["metadata"]),
            )
        )
    return stats


def _persist_subdoc_cards(
    db: Session,
    document: Document,
    subdoc: SubDocument,
    breadcrumb_key: str,
    pages: list[dict],
    parent_sections: dict,
) -> None:
    page_titles = [p["title"] for p in pages]
    db.add(
        LibraryCard(
            collection_id=document.collection_id,
            document_id=document.id,
            sub_document_id=subdoc.id,
            doc_id=f"subdoc_{subdoc.id}",
            level="subdocument",
            title=breadcrumb_key,
            content=(
                f"Contains {len(pages)} pages: "
                f"{', '.join(page_titles[:5])}"
                f"{'...' if len(page_titles) > 5 else ''}"
            ),
            extra_metadata=json.dumps(
                {
                    "page_titles": page_titles,
                    "faiss_path": subdoc.faiss_index_path,
                    "bm25_path": subdoc.bm25_index_path,
                    "extraction_time": time.time(),
                }
            ),
        )
    )
    for doc_id, section_data in parent_sections.items():
        db.add(
            LibraryCard(
                collection_id=document.collection_id,
                document_id=document.id,
                sub_document_id=subdoc.id,
                doc_id=doc_id,
                level=section_data["level"],
                title=section_data["title"],
                content=strip_section_images(section_data["content"]),
                extra_metadata=json.dumps(
                    {
                        "extraction_time": time.time(),
                        "start_char": section_data.get("start_char", 0),
                        "end_char": section_data.get("end_char", 0),
                    }
                ),
            )
        )


def _resolve_subdoc_citations(db: Session, subdoc_id: int) -> None:
    """Resolve chunk citation library_card_doc_id → library_card_id."""
    library_cards_map = {}
    for card in (
        db.query(LibraryCard)
        .filter(
            LibraryCard.sub_document_id == subdoc_id,
            LibraryCard.level.in_(["level_1", "level_2", "level_3"]),
        )
        .all()
    ):
        library_cards_map[card.doc_id] = card.id

    subdoc_chunks = db.query(Chunk).filter(Chunk.sub_document_id == subdoc_id).all()
    for chunk in subdoc_chunks:
        metadata = json.loads(chunk.chunk_metadata)
        citation = metadata.get("citation")
        if citation and citation.get("library_card_doc_id"):
            doc_id = citation["library_card_doc_id"]
            if doc_id in library_cards_map:
                citation["library_card_id"] = library_cards_map[doc_id]
                del citation["library_card_doc_id"]
                chunk.chunk_metadata = json.dumps(metadata)
            else:
                logger.warning(
                    "Could not resolve library_card_doc_id '%s' for chunk %s",
                    doc_id,
                    chunk.chunk_index,
                )
