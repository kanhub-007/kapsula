"""SQLAlchemy-backed DocumentRepository — maps between domain and ORM."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from doc_search.core.domain.entities.document import Document as DomainDocument
from doc_search.core.domain.entities.collection import Collection as DomainCollection
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
from doc_search.infrastructure.repositories.data.mappers import (
    document_from_orm,
    document_to_orm,
    collection_from_orm,
)
from doc_search.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class SqlDocumentRepository(DocumentRepository):
    """Persists documents via SQLAlchemy, mapping through domain entities."""

    def find_document_by_job_id(
        self, db: Session, job_id: str
    ) -> DomainDocument | None:
        orm_doc = db.query(Document).filter(Document.job_id == job_id).first()
        if orm_doc is None:
            return None
        return document_from_orm(orm_doc)

    def find_collection_by_guid(
        self, db: Session, collection_id: str
    ) -> DomainCollection | None:
        orm_col = (
            db.query(Collection)
            .filter(Collection.collection_id == collection_id)
            .first()
        )
        if orm_col is None:
            return None
        return collection_from_orm(orm_col)

    def save_document(self, db: Session, document: DomainDocument) -> None:
        orm_doc = document_to_orm(document)
        db.add(orm_doc)
        db.commit()
        db.refresh(orm_doc)
        # Push back generated ID
        document.id = orm_doc.id

    def cascade_delete_related(self, db: Session, document: DomainDocument) -> int:
        if document.id is None:
            return 0
        doc_id = document.id

        chunks_deleted = (
            db.query(Chunk).filter(Chunk.document_id == doc_id).delete()
        )

        sub_doc_ids = select(SubDocument.id).where(
            SubDocument.document_id == doc_id
        )
        db.query(SubDocumentPage).filter(
            SubDocumentPage.sub_document_id.in_(sub_doc_ids)
        ).delete(synchronize_session=False)

        db.query(SubDocument).filter(SubDocument.document_id == doc_id).delete()
        db.query(LibraryCard).filter(LibraryCard.document_id == doc_id).delete()
        db.query(DocumentStructure).filter(
            DocumentStructure.document_id == doc_id
        ).delete()

        return chunks_deleted

    def mark_archived(self, db: Session, document: DomainDocument) -> None:
        if document.id is None:
            return
        orm_doc = db.query(Document).filter(Document.id == document.id).first()
        if orm_doc:
            orm_doc.doc_state = "archived"
            orm_doc.status = "archived"
            db.commit()
