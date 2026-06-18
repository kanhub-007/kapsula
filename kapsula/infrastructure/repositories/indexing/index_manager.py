"""Filesystem-based search index manager."""

import os

from sqlalchemy.orm import Session

from kapsula.core.domain.interfaces.embedder import Embedder
from kapsula.core.domain.interfaces.index_manager import (
    IndexManager,
    IndexableDocument,
    IndexableSubDocument,
    IndexableCollection,
)
from kapsula.core.domain.entities.aggregate_index_paths import (
    AggregateIndexPaths,
)
from kapsula.core.domain.entities.rebuild_result import RebuildResult
from kapsula.infrastructure.repositories.indexing.aggregate_index_builder import (
    AggregateIndexBuilder,
)
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class FileSystemIndexManager(IndexManager):
    """Manages index files on the local filesystem."""

    def __init__(self, embedder: Embedder, data_dir: str):
        self._data_dir = data_dir
        self._builder = AggregateIndexBuilder(embedder, data_dir)

    # ── document-level indexes ──────────────────────────────────

    def delete_document_indexes(self, document: IndexableDocument) -> None:
        """Delete FAISS and BM25 index files for a document."""
        for attr in ("faiss_index_path", "bm25_index_path"):
            path = getattr(document, attr, None)
            if path and os.path.exists(path):
                os.remove(path)
                logger.debug("Deleted document index: %s", path)

        self.delete_sub_document_indexes(document.sub_documents)

    def delete_sub_document_indexes(
        self, sub_documents: list[IndexableSubDocument]
    ) -> None:
        """Delete FAISS and BM25 index files for sub-documents."""
        for sd in sub_documents:
            for attr in ("faiss_index_path", "bm25_index_path"):
                path = getattr(sd, attr, None)
                if path and os.path.exists(path):
                    os.remove(path)

    # ── aggregate cache ─────────────────────────────────────────

    def invalidate_aggregate_cache(self, collection: IndexableCollection) -> None:
        """Delete aggregate cache files so the next build is a full rebuild."""
        account = collection.account if collection.account else None
        account_guid = account.account_id if account else None

        coll_paths = AggregateIndexPaths.for_collection(
            self._data_dir, account_guid, collection.collection_id
        )
        for p in (coll_paths.faiss, coll_paths.bm25, coll_paths.mapping, coll_paths.faiss_npy):
            if p and os.path.exists(p):
                os.remove(p)
                logger.debug("Deleted aggregate cache: %s", os.path.basename(p))

        if account_guid:
            acct_paths = AggregateIndexPaths.for_account(self._data_dir, account_guid)
            for p in (acct_paths.faiss, acct_paths.bm25, acct_paths.mapping, acct_paths.faiss_npy):
                if p and os.path.exists(p):
                    os.remove(p)

    # ── rebuild ─────────────────────────────────────────────────

    def rebuild_aggregates(
        self, db: Session, collection: IndexableCollection
    ) -> RebuildResult:
        """Rebuild collection and account aggregate indexes."""
        account = collection.account if collection.account else None
        account_guid = account.account_id if account else None

        result = RebuildResult()

        coll_faiss, coll_bm25 = self._builder.build(
            db,
            collection.id,
            account_id=account_guid,
            collection_guid=collection.collection_id,
        )
        result.collection_faiss = coll_faiss
        result.collection_bm25 = coll_bm25

        if account:
            acct_faiss, acct_bm25 = self._builder.build_account(
                db, account.id, account.account_id
            )
            result.account_faiss = acct_faiss
            result.account_bm25 = acct_bm25

        return result
