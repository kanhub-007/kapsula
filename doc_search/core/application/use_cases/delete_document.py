"""Delete document use case — archives document, removes chunks, rebuilds indexes."""

from sqlalchemy.orm import Session

from doc_search.core.application.dto.delete_document_result import (
    DeleteDocumentResult,
)
from doc_search.core.domain.interfaces.index_manager import IndexManager
from doc_search.infrastructure.data import (
    Document,
    Chunk,
    LibraryCard,
    SubDocument,
    SubDocumentPage,
    DocumentStructure,
)
from doc_search.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class DeleteDocumentUseCase:
    """Soft-deletes a document: archives it, cascade-deletes related records,
    removes index files, and rebuilds aggregate indexes."""

    def __init__(self, index_manager: IndexManager):
        self._index_manager = index_manager

    def execute(self, db: Session, job_id: str) -> DeleteDocumentResult:
        """Execute the delete operation.

        Args:
            db: Database session.
            job_id: The job_id (GUID) of the document to delete.

        Returns:
            DeleteDocumentResult with details about the operation.

        Raises:
            ValueError: If the document is not found.
        """
        doc = db.query(Document).filter(Document.job_id == job_id).first()
        if not doc:
            raise ValueError(f"Document not found: {job_id}")

        filename = doc.filename
        collection = doc.collection
        collection_name = collection.name if collection else "?"

        logger.info(
            "Deleting document: job_id=%s filename=%s collection=%s",
            job_id,
            filename,
            collection_name,
        )

        # 1. Delete index files from disk (before DB changes)
        self._index_manager.delete_document_indexes(doc)

        # 2. Invalidate aggregate caches
        if collection:
            self._index_manager.invalidate_aggregate_cache(collection)

        # 3. Cascade-delete related records from database
        chunks_deleted = self._cascade_delete_records(db, doc)

        # 4. Mark document as archived (soft delete)
        doc.doc_state = "archived"
        doc.status = "archived"
        db.commit()

        # 5. Rebuild aggregate indexes
        rebuild_result: dict[str, str | None] = {}
        rebuild_error: str | None = None

        if collection:
            try:
                rebuild_result = self._index_manager.rebuild_aggregates(db, collection)
            except Exception as exc:
                logger.error("Aggregate rebuild failed after delete: %s", exc)
                rebuild_error = str(exc)
                # Populate with failure markers
                rebuild_result = {
                    "collection_faiss": None,
                    "collection_bm25": None,
                    "account_faiss": None,
                    "account_bm25": None,
                }

        logger.info(
            "Document deleted: job_id=%s chunks=%s", job_id, chunks_deleted
        )

        return DeleteDocumentResult(
            job_id=job_id,
            filename=filename,
            collection_name=collection_name,
            chunks_deleted=chunks_deleted,
            rebuild=rebuild_result,
            error=rebuild_error,
        )

    # ── private helpers ─────────────────────────────────────────

    @staticmethod
    def _cascade_delete_records(db: Session, doc: Document) -> int:
        """Delete all related records for a document. Returns count of deleted chunks."""
        chunks_deleted = (
            db.query(Chunk).filter(Chunk.document_id == doc.id).delete()
        )

        # Bulk-delete sub-document pages via subquery
        from sqlalchemy import select
        sub_doc_ids = (
            select(SubDocument.id)
            .where(SubDocument.document_id == doc.id)
        )
        db.query(SubDocumentPage).filter(
            SubDocumentPage.sub_document_id.in_(sub_doc_ids)
        ).delete(synchronize_session=False)

        db.query(SubDocument).filter(SubDocument.document_id == doc.id).delete()
        db.query(LibraryCard).filter(LibraryCard.document_id == doc.id).delete()
        db.query(DocumentStructure).filter(
            DocumentStructure.document_id == doc.id
        ).delete()

        return chunks_deleted
