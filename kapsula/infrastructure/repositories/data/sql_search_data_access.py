"""SQLAlchemy implementation of SearchDataAccess.

Returns application read-models (DTOs), never ORM instances, so the
application layer stays decoupled from SQLAlchemy. Account persistence
lives on ``AccountRepository`` instead.
"""

from sqlalchemy.orm import Session

from kapsula.core.application.dto.collection_read import CollectionRead
from kapsula.core.application.dto.document_read import DocumentRead
from kapsula.core.application.dto.sub_document_read import SubDocumentRead
from kapsula.infrastructure.data.tables.chunk import Chunk
from kapsula.infrastructure.data.tables.collection import Collection
from kapsula.infrastructure.data.tables.document import Document
from kapsula.infrastructure.data.tables.library_card import LibraryCard
from kapsula.infrastructure.data.tables.sub_document import SubDocument
from kapsula.infrastructure.repositories.data.mappers import (
    collection_to_read,
    document_to_read,
    sub_document_to_read,
)


class SqlSearchDataAccess:
    """SQLAlchemy-backed data access for search use cases."""

    def __init__(self, db: Session):
        self._db = db

    def get_sub_documents(self, document_id: int) -> list[SubDocumentRead]:
        orm_list = (
            self._db.query(SubDocument)
            .filter(SubDocument.document_id == document_id)
            .all()
        )
        return [sub_document_to_read(s) for s in orm_list]

    def get_completed_documents(self, collection_id: int) -> list[DocumentRead]:
        orm_list = (
            self._db.query(Document)
            .filter(
                Document.collection_id == collection_id,
                Document.status == "completed",
            )
            .all()
        )
        return [document_to_read(d) for d in orm_list]

    def get_collections_by_account(self, account_id: str) -> list[CollectionRead]:
        orm_list = (
            self._db.query(Collection)
            .join(Collection.account)
            .filter(Collection.account.has(account_id=account_id))
            .all()
        )
        return [collection_to_read(c) for c in orm_list]

    def get_collection_by_collection_id(
        self, collection_id: str
    ) -> CollectionRead | None:
        orm = (
            self._db.query(Collection)
            .filter(Collection.collection_id == collection_id)
            .first()
        )
        return collection_to_read(orm) if orm else None

    def get_all_collections(self) -> list[CollectionRead]:
        orm_list = self._db.query(Collection).all()
        return [collection_to_read(c) for c in orm_list]

    def get_collection_library_card(self, collection_id: int):
        return (
            self._db.query(LibraryCard)
            .filter(
                LibraryCard.collection_id == collection_id,
                LibraryCard.level == "collection",
            )
            .first()
        )

    def get_library_card_for_sub_doc(self, sub_doc_id: int):
        return (
            self._db.query(LibraryCard)
            .filter(LibraryCard.sub_document_id == sub_doc_id)
            .first()
        )

    def get_library_card_by_doc_id(self, doc_id: str, sub_doc_id: int | None = None):
        query = self._db.query(LibraryCard).filter(LibraryCard.doc_id == doc_id)
        if sub_doc_id is not None:
            query = query.filter(LibraryCard.sub_document_id == sub_doc_id)
        return query.first()

    def get_chunk(
        self,
        document_id: int,
        chunk_index: int,
        sub_doc_id: int | None = None,
    ):
        query = self._db.query(Chunk).filter(
            Chunk.document_id == document_id,
            Chunk.chunk_index == chunk_index,
        )
        if sub_doc_id is not None:
            query = query.filter(Chunk.sub_document_id == sub_doc_id)
        return query.first()

    def get_chunks_batch(
        self,
        document_id: int,
        chunk_specs: list[tuple[int, int | None]],
    ) -> dict:
        """Fetch multiple chunks in a single DB query.

        Returns a dict mapping ``(chunk_index, sub_doc_id)`` to Chunk ORM.
        """
        if not chunk_specs:
            return {}
        from sqlalchemy import or_

        conditions = []
        for c_idx, s_id in chunk_specs:
            if s_id is not None:
                conditions.append(
                    (Chunk.chunk_index == c_idx) & (Chunk.sub_document_id == s_id)
                )
            else:
                conditions.append(Chunk.chunk_index == c_idx)
        chunks = (
            self._db.query(Chunk)
            .filter(Chunk.document_id == document_id, or_(*conditions))
            .all()
        )
        result: dict = {}
        for c in chunks:
            result[(c.chunk_index, c.sub_document_id)] = c
        return result

    def get_library_cards_by_doc_ids(self, doc_ids: list[str]) -> dict:
        """Fetch multiple library cards by doc_id in a single DB query.

        Returns a dict mapping doc_id to LibraryCard ORM.
        """
        if not doc_ids:
            return {}
        cards = (
            self._db.query(LibraryCard).filter(LibraryCard.doc_id.in_(doc_ids)).all()
        )
        return {c.doc_id: c for c in cards}

    def count_sub_documents(self, document_id: int) -> int:
        return (
            self._db.query(SubDocument)
            .filter(SubDocument.document_id == document_id)
            .count()
        )
