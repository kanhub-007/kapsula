"""SQLAlchemy implementation of SearchDataAccess."""

from sqlalchemy.orm import Session

from kapsula.infrastructure.data.tables.account import Account
from kapsula.infrastructure.data.tables.collection import Collection
from kapsula.infrastructure.data.tables.document import Document
from kapsula.infrastructure.data.tables.chunk import Chunk
from kapsula.infrastructure.data.tables.library_card import LibraryCard
from kapsula.infrastructure.data.tables.sub_document import SubDocument


class SqlSearchDataAccess:
    """SQLAlchemy-backed data access for search use cases."""

    def __init__(self, db: Session):
        self._db = db

    def get_sub_documents(self, document_id: int) -> list:
        return (
            self._db.query(SubDocument)
            .filter(SubDocument.document_id == document_id)
            .all()
        )

    def get_completed_documents(self, collection_id: int) -> list:
        return (
            self._db.query(Document)
            .filter(
                Document.collection_id == collection_id,
                Document.status == "completed",
            )
            .all()
        )

    def get_collections_by_account(self, account_id: str) -> list:
        return (
            self._db.query(Collection)
            .join(Collection.account)
            .filter(Collection.account.has(account_id=account_id))
            .all()
        )

    def get_collection_by_collection_id(self, collection_id: str):
        return (
            self._db.query(Collection)
            .filter(Collection.collection_id == collection_id)
            .first()
        )

    def get_all_collections(self) -> list:
        return self._db.query(Collection).all()

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

    def count_sub_documents(self, document_id: int) -> int:
        return (
            self._db.query(SubDocument)
            .filter(SubDocument.document_id == document_id)
            .count()
        )

    def get_account_by_name(self, name: str):
        return self._db.query(Account).filter(Account.name == name).first()

    def save_account(self, account) -> None:
        """Persist an account and return it with the generated identity."""
        self._db.add(account)
        self._db.commit()
        self._db.refresh(account)
        return account
