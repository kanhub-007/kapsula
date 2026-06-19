"""SQLAlchemy-backed LibraryCardRepository."""

from sqlalchemy.orm import Session

from kapsula.core.domain.entities.library_card import LibraryCard as DomainCard
from kapsula.core.domain.interfaces.library_card_repository import (
    LibraryCardRepository,
)
from kapsula.infrastructure.data import LibraryCard as OrmLibraryCard
from kapsula.infrastructure.repositories.data.mappers import library_card_from_orm


class SqlLibraryCardRepository(LibraryCardRepository):
    """SQLAlchemy-backed library card queries."""

    def find_collection_card(
        self, db: Session, collection_id: int
    ) -> DomainCard | None:
        orm = (
            db.query(OrmLibraryCard)
            .filter(
                OrmLibraryCard.collection_id == collection_id,
                OrmLibraryCard.level == "collection",
            )
            .first()
        )
        return library_card_from_orm(orm) if orm else None

    def count_by_document(self, db: Session, document_id: int) -> int:
        return (
            db.query(OrmLibraryCard)
            .filter(OrmLibraryCard.document_id == document_id)
            .count()
        )
