"""SQLAlchemy-backed SubDocumentRepository."""

from sqlalchemy.orm import Session

from kapsula.core.domain.entities.sub_document import (
    SubDocument as DomainSubDoc,
)
from kapsula.core.domain.interfaces.sub_document_repository import (
    SubDocumentRepository,
)
from kapsula.infrastructure.data import SubDocument as OrmSubDocument
from kapsula.infrastructure.repositories.data.mappers import sub_document_from_orm


class SqlSubDocumentRepository(SubDocumentRepository):
    """SQLAlchemy-backed sub-document queries."""

    def list_by_document(self, db: Session, document_id: int) -> list[DomainSubDoc]:
        orm_list = (
            db.query(OrmSubDocument)
            .filter(OrmSubDocument.document_id == document_id)
            .all()
        )
        return [sub_document_from_orm(s) for s in orm_list]
