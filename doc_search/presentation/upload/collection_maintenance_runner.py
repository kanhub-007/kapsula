"""Collection maintenance runner."""

import json

from sqlalchemy.orm import Session

from doc_search.infrastructure.data import Collection, Document, LibraryCard, DATA_DIR
from doc_search.infrastructure.logging_config import get_logger
from doc_search.infrastructure.repositories.indexing.aggregate_index_builder import (
    AggregateIndexBuilder,
)
from doc_search.presentation.upload.maintenance_state_manager import (
    MaintenanceStateManager,
)
from doc_search.startup import create_embedder

logger = get_logger(__name__)


class CollectionMaintenanceRunner:
    """Runs deferred summary and aggregate-index maintenance for a collection."""

    def __init__(self, db: Session):
        self._db = db

    def run(self, collection: Collection) -> dict:
        """Run collection summary and aggregate-index maintenance."""
        summary_updates, summary_failures = self._refresh_collection_summary(collection)
        aggregate_result = self._rebuild_aggregate_indexes(collection)
        MaintenanceStateManager().mark_collection_fresh(
            collection,
            summary=summary_failures == 0,
            collection_index=aggregate_result["collection_index_updated"],
            account_index=aggregate_result["account_index_updated"],
        )
        return {
            "collection_id": collection.collection_id,
            "collection_name": collection.name,
            "summary_updates": summary_updates,
            "summary_failures": summary_failures,
            **aggregate_result,
        }

    def _refresh_collection_summary(self, collection: Collection) -> tuple[int, int]:
        from doc_search.presentation.api.tasks import update_collection_library_card

        existing_document_ids = self._existing_summary_document_ids(collection)
        completed_docs = (
            self._db.query(Document)
            .filter(
                Document.collection_id == collection.id,
                Document.status == "completed",
            )
            .order_by(Document.created_at.asc())
            .all()
        )
        missing_docs = [
            doc for doc in completed_docs if doc.id not in existing_document_ids
        ]
        successes = 0
        failures = 0
        for document in missing_docs:
            try:
                update_collection_library_card(document.id, self._db)
                successes += 1
            except Exception as exc:
                failures += 1
                logger.error(
                    "Collection maintenance failed to summarize document %s: %s",
                    document.job_id,
                    exc,
                    exc_info=True,
                )
        return successes, failures

    def _existing_summary_document_ids(self, collection: Collection) -> set[int]:
        card = (
            self._db.query(LibraryCard)
            .filter(
                LibraryCard.collection_id == collection.id,
                LibraryCard.level == "collection",
            )
            .first()
        )
        if not card or not card.extra_metadata:
            return set()
        try:
            metadata = json.loads(card.extra_metadata)
        except json.JSONDecodeError:
            logger.warning(
                "Failed to parse collection library card metadata for collection %s",
                collection.collection_id,
            )
            return set()
        return {
            int(item["document_id"])
            for item in metadata.get("document_summaries", [])
            if item.get("document_id") is not None
        }

    def _rebuild_aggregate_indexes(self, collection: Collection) -> dict:
        embedder = create_embedder()
        builder = AggregateIndexBuilder(embedder, DATA_DIR)
        account = collection.account
        account_guid = account.account_id if account else None

        collection_faiss, collection_bm25 = builder.build(
            self._db,
            collection_id=collection.id,
            account_id=account_guid,
            collection_guid=collection.collection_id,
        )
        account_faiss = None
        account_bm25 = None
        if account:
            account_faiss, account_bm25 = builder.build_account(
                self._db,
                account_id=account.id,
                account_guid=account.account_id,
            )
        return {
            "collection_faiss": collection_faiss,
            "collection_bm25": collection_bm25,
            "account_faiss": account_faiss,
            "account_bm25": account_bm25,
            "collection_index_updated": bool(collection_faiss or collection_bm25),
            "account_index_updated": bool(account_faiss or account_bm25) or not account,
        }
