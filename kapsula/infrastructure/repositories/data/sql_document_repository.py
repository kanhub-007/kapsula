"""SQLAlchemy-backed DocumentRepository — maps between domain and ORM."""

from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from kapsula.core.domain.entities.document import Document as DomainDocument
from kapsula.core.domain.entities.collection import Collection as DomainCollection
from kapsula.core.domain.interfaces.document_repository import (
    DocumentRepository,
)
from kapsula.infrastructure.data import (
    Document,
    Collection,
    Chunk,
    SubDocument,
    SubDocumentPage,
    LibraryCard,
    DocumentStructure,
)
from kapsula.infrastructure.repositories.data.mappers import (
    document_from_orm,
    document_to_orm,
    collection_from_orm,
)
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class SqlDocumentRepository(DocumentRepository):
    """Persists documents via SQLAlchemy, mapping through domain entities."""

    def list_all(self, db: Session) -> list[DomainDocument]:
        orm_list = db.query(Document).order_by(Document.created_at.desc()).all()
        return [document_from_orm(d) for d in orm_list]

    def list_by_collection(
        self, db: Session, collection_guid: str
    ) -> list[DomainDocument]:
        col = (
            db.query(Collection)
            .filter(Collection.collection_id == collection_guid)
            .first()
        )
        if col is None:
            return []
        orm_list = (
            db.query(Document)
            .filter(Document.collection_id == col.id)
            .order_by(Document.created_at.desc())
            .all()
        )
        return [document_from_orm(d) for d in orm_list]

    def find_document_by_job_id(
        self, db: Session, job_id: str
    ) -> DomainDocument | None:
        from sqlalchemy.orm import joinedload
        orm_doc = (
            db.query(Document)
            .options(
                joinedload(Document.collection).joinedload(Collection.account)
            )
            .filter(Document.job_id == job_id)
            .first()
        )
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

    def save_document(self, db: Session, document: DomainDocument) -> DomainDocument:
        orm_doc = document_to_orm(document)
        db.add(orm_doc)
        db.commit()
        db.refresh(orm_doc)
        return replace(document, id=orm_doc.id)

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
