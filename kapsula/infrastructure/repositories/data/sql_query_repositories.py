"""SQLAlchemy-backed query repositories (read-only)."""

from sqlalchemy.orm import Session

from kapsula.core.domain.entities.chunk import Chunk as DomainChunk
from kapsula.core.domain.entities.library_card import LibraryCard as DomainCard
from kapsula.core.domain.entities.sub_document import SubDocument as DomainSubDoc
from kapsula.core.domain.interfaces.query_repositories import (
    ChunkRepository,
    LibraryCardRepository,
    SubDocumentRepository,
)
from kapsula.infrastructure.data import (
    Chunk as OrmChunk,
)
from kapsula.infrastructure.data import (
    LibraryCard as OrmLibraryCard,
)
from kapsula.infrastructure.data import (
    SubDocument as OrmSubDocument,
)
from kapsula.infrastructure.repositories.data.mappers import (
    chunk_from_orm,
    sub_document_from_orm,
)


class SqlChunkRepository(ChunkRepository):
    """SQLAlchemy-backed chunk queries."""

    def list_by_document(self, db: Session, document_id: int) -> list[DomainChunk]:
        orm_list = (
            db.query(OrmChunk)
            .filter(OrmChunk.document_id == document_id)
            .order_by(OrmChunk.chunk_index)
            .all()
        )
        return [chunk_from_orm(c) for c in orm_list]

    def count_by_document(self, db: Session, document_id: int) -> int:
        return db.query(OrmChunk).filter(OrmChunk.document_id == document_id).count()


class SqlSubDocumentRepository(SubDocumentRepository):
    """SQLAlchemy-backed sub-document queries."""

    def list_by_document(self, db: Session, document_id: int) -> list[DomainSubDoc]:
        orm_list = (
            db.query(OrmSubDocument)
            .filter(OrmSubDocument.document_id == document_id)
            .all()
        )
        return [sub_document_from_orm(s) for s in orm_list]


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
        if orm is None:
            return None
        return DomainCard(
            id=orm.id,
            collection_id=orm.collection_id,
            document_id=orm.document_id,
            sub_document_id=orm.sub_document_id,
            doc_id=orm.doc_id,
            level=orm.level,
            title=orm.title,
            content=orm.content,
            extra_metadata=orm.extra_metadata,
            created_at=orm.created_at,
        )

    def count_by_document(self, db: Session, document_id: int) -> int:
        return (
            db.query(OrmLibraryCard)
            .filter(OrmLibraryCard.document_id == document_id)
            .count()
        )
