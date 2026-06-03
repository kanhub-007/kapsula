"""Interface for managing search index files on disk."""

from abc import ABC, abstractmethod
from typing import Any, Protocol

from sqlalchemy.orm import Session


class IndexableSubDocument(Protocol):
    """Protocol for sub-documents that have index file paths."""
    faiss_index_path: str | None
    bm25_index_path: str | None


class IndexableDocument(Protocol):
    """Protocol for documents that have index file paths and sub-documents."""
    faiss_index_path: str | None
    bm25_index_path: str | None
    sub_documents: list[IndexableSubDocument]


class IndexableCollection(Protocol):
    """Protocol for collections with an account and GUID."""
    id: int
    collection_id: str
    account: Any | None  # has .account_id


class IndexManager(ABC):
    """Manages document-level and aggregate search index lifecycle."""

    @abstractmethod
    def delete_document_indexes(self, document: IndexableDocument) -> None:
        """Delete FAISS and BM25 index files for a document and its sub-documents."""

    @abstractmethod
    def invalidate_aggregate_cache(self, collection: IndexableCollection) -> None:
        """Delete aggregate cache files (FAISS, BM25, mapping, embeddings)
        to force a full rebuild on the next aggregate index build."""

    @abstractmethod
    def rebuild_aggregates(
        self, db: Session, collection: IndexableCollection
    ) -> dict[str, str | None]:
        """Rebuild collection and account aggregate indexes.
        
        Returns a dict with keys: collection_faiss, collection_bm25,
        account_faiss, account_bm25."""

    @abstractmethod
    def delete_sub_document_indexes(
        self, sub_documents: list[IndexableSubDocument]
    ) -> None:
        """Delete FAISS and BM25 index files for a list of sub-documents."""
