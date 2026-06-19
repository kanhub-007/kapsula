"""SQLAlchemy-backed ChunkRepository."""

from sqlalchemy.orm import Session

from kapsula.core.domain.entities.chunk import Chunk as DomainChunk
from kapsula.core.domain.interfaces.chunk_repository import ChunkRepository
from kapsula.infrastructure.data import Chunk as OrmChunk
from kapsula.infrastructure.repositories.data.mappers import chunk_from_orm


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
