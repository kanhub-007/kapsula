"""SQLAlchemy-backed DocumentRepository implementation."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from doc_search.core.domain.interfaces.document_repository import (
    DocumentRepository,
)
from doc_search.infrastructure.data import (
    Document,
    Collection,
    Chunk,
    SubDocument,
    SubDocumentPage,
    LibraryCard,
    DocumentStructure,
)
from doc_search.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class SqlDocumentRepository(DocumentRepository):
    """Persists documents and collections via SQLAlchemy ORM."""

    def find_document_by_job_id(self, db: Session, job_id: str):
        return db.query(Document).filter(Document.job_id == job_id).first()

    def find_collection_by_guid(self, db: Session, collection_id: str):
        return (
            db.query(Collection)
            .filter(Collection.collection_id == collection_id)
            .first()
        )

    def save_document(self, db: Session, document: Document) -> None:
        db.add(document)
        db.commit()
        db.refresh(document)

    def cascade_delete_related(self, db: Session, document: Document) -> int:
        """Delete chunks, sub-documents, pages, cards, and structure."""
        chunks_deleted = (
            db.query(Chunk)
            .filter(Chunk.document_id == document.id)
            .delete()
        )

        sub_doc_ids = (
            select(SubDocument.id)
            .where(SubDocument.document_id == document.id)
        )
        db.query(SubDocumentPage).filter(
            SubDocumentPage.sub_document_id.in_(sub_doc_ids)
        ).delete(synchronize_session=False)

        db.query(SubDocument).filter(
            SubDocument.document_id == document.id
        ).delete()
        db.query(LibraryCard).filter(
            LibraryCard.document_id == document.id
        ).delete()
        db.query(DocumentStructure).filter(
            DocumentStructure.document_id == document.id
        ).delete()

        return chunks_deleted

    def mark_archived(self, db: Session, document: Document) -> None:
        document.doc_state = "archived"
        document.status = "archived"
        db.commit()
