"""Interface for managing search index files on disk."""

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.orm import Session


class IndexManager(ABC):
    """Manages document-level and aggregate search index lifecycle."""

    @abstractmethod
    def delete_document_indexes(self, document: Any) -> None:
        """Delete FAISS and BM25 index files for a document and its sub-documents."""

    @abstractmethod
    def invalidate_aggregate_cache(self, collection: Any) -> None:
        """Delete aggregate cache files (FAISS, BM25, mapping, embeddings)
        to force a full rebuild on the next aggregate index build."""

    @abstractmethod
    def rebuild_aggregates(
        self, db: Session, collection: Any
    ) -> dict[str, str | None]:
        """Rebuild collection and account aggregate indexes.
        
        Returns a dict with keys: collection_faiss, collection_bm25,
        account_faiss, account_bm25."""

    @abstractmethod
    def delete_sub_document_indexes(self, sub_documents: list[Any]) -> None:
        """Delete FAISS and BM25 index files for a list of sub-documents."""
