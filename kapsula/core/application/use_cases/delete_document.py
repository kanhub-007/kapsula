"""Delete document use case — archives document, removes chunks, rebuilds indexes."""

from sqlalchemy.orm import Session

from kapsula.core.application.dto.delete_document_result import (
    DeleteDocumentResult,
)
from kapsula.core.application.dto.rebuild_result import RebuildResult
from kapsula.core.domain.interfaces.index_manager import IndexManager
from kapsula.core.domain.interfaces.document_repository import (
    DocumentRepository,
)
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class DeleteDocumentUseCase:
    """Soft-deletes a document: archives it, cascade-deletes related records,
    removes index files, and rebuilds aggregate indexes."""

    def __init__(
        self,
        index_manager: IndexManager,
        document_repository: DocumentRepository,
    ):
        self._index_manager = index_manager
        self._document_repository = document_repository

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
        doc = self._document_repository.find_document_by_job_id(db, job_id)
        if not doc:
            raise ValueError(f"Document not found: {job_id}")

        filename = doc.filename
        collection = doc.collection
        collection_name = collection.name if collection else "?"

        logger.info(
            "Deleting document: job_id=%s filename=%s collection=%s",
            job_id, filename, collection_name,
        )

        # 1. Delete index files from disk (before DB changes)
        self._index_manager.delete_document_indexes(doc)

        # 2. Invalidate aggregate caches
        if collection:
            self._index_manager.invalidate_aggregate_cache(collection)

        # 3. Cascade-delete related records (via repository)
        chunks_deleted = self._document_repository.cascade_delete_related(db, doc)

        # 4. Mark document as archived (soft delete)
        self._document_repository.mark_archived(db, doc)

        # 5. Rebuild aggregate indexes
        rebuild: RebuildResult | None = None
        rebuild_error: str | None = None

        if collection:
            try:
                rebuild = self._index_manager.rebuild_aggregates(db, collection)
            except Exception as exc:
                logger.error("Aggregate rebuild failed after delete: %s", exc)
                rebuild_error = str(exc)

        logger.info("Document deleted: job_id=%s chunks=%s", job_id, chunks_deleted)

        return DeleteDocumentResult(
            job_id=job_id,
            filename=filename,
            collection_name=collection_name,
            chunks_deleted=chunks_deleted,
            rebuild=rebuild,
            error=rebuild_error,
        )
