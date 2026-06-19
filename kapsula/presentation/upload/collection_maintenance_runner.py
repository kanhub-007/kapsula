"""Collection maintenance runner."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from kapsula.infrastructure.data import (
    DATA_DIR,
    Collection,
    Document,
    LibraryCard,
    SessionLocal,
)
from kapsula.infrastructure.logging_config import get_logger
from kapsula.infrastructure.repositories.indexing.aggregate_index_builder import (
    AggregateIndexBuilder,
)
from kapsula.startup import (
    create_embedder,
    create_maintenance_state_manager,
)

if TYPE_CHECKING:
    from kapsula.core.domain.interfaces.chat_client import ChatClient

logger = get_logger(__name__)


class CollectionMaintenanceRunner:
    """Runs deferred summary and aggregate-index maintenance for a collection.

    The chat client is injected (closes H9) so this presentation module no
    longer imports from the MCP tools package. Callers pass the shared,
    cached client from :func:`kapsula.startup.get_shared_chat_client`.
    """

    def __init__(self, db: Session, chat_client: ChatClient | None = None):
        self._db = db
        self._chat_client = chat_client

    def _chat(self):
        """Return the injected chat client, or lazily fetch the shared one."""
        if self._chat_client is None:
            from kapsula.startup import get_shared_chat_client

            self._chat_client = get_shared_chat_client()
        return self._chat_client

    def run(self, collection: Collection, progress_callback=None) -> dict:
        """Run collection summary, aggregate-index, and consolidation maintenance.

        Args:
            collection: The ORM collection to maintain.
            progress_callback: Optional callable(stage, progress, detail) for progress reporting.
        """
        if progress_callback:
            progress_callback("summarizing", "Counting documents...", "")
        summary_updates, summary_failures = self._refresh_collection_summary(
            collection, progress_callback
        )
        if progress_callback:
            progress_callback("indexing", "Rebuilding FAISS+BM25 indexes...", "")
        aggregate_result = self._rebuild_aggregate_indexes(collection)
        state_mgr = create_maintenance_state_manager()

        # Phase 3: consolidation (check BEFORE marking fresh, runs if stale)
        consolidation_result: dict = {}
        if state_mgr.list_stale():
            col_stale = [
                s
                for s in state_mgr.list_stale()
                if s.get("collection_id") == collection.collection_id
                and s.get("consolidation_stale")
            ]
            if col_stale:
                if progress_callback:
                    progress_callback(
                        "consolidating", "Running knowledge consolidation...", ""
                    )
                try:
                    from kapsula.infrastructure.repositories.data.sql_consolidation_card_repository import (
                        SqlConsolidationCardRepository,
                    )
                    from kapsula.infrastructure.repositories.processing.consolidation_runner import (
                        ConsolidationRunner,
                    )

                    chat_client = self._chat()
                    card_repository = SqlConsolidationCardRepository(SessionLocal)
                    runner = ConsolidationRunner(
                        card_repository,
                        chat_client,
                        collection.id,
                        collection.collection_id,
                    )
                    consolidation_result = runner.run()
                    state_mgr.mark_consolidated(collection.collection_id)
                except Exception as exc:
                    logger.exception(
                        "Consolidation failed for collection %s: %s",
                        collection.collection_id,
                        exc,
                    )
                    consolidation_result = {"error": str(exc)}

        # Slice 2: enrich terse structural titles with one-line descriptions
        enrichment_result = self._enrich_structural_cards(collection, progress_callback)

        # Mark fresh AFTER consolidation attempt
        state_mgr.mark_collection_fresh(
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
            **consolidation_result,
            "cards_enriched": enrichment_result.get("enriched", 0),
        }

    def _enrich_structural_cards(
        self, collection: Collection, progress_callback=None
    ) -> dict:
        """Enrich terse structural titles with one-line descriptions (Slice 2)."""
        if progress_callback:
            progress_callback("enriching", "Enriching structural card titles...", "")
        try:
            from kapsula.infrastructure.repositories.processing.card_enricher import (
                CardEnricher,
            )

            enricher = CardEnricher(
                SessionLocal,
                self._chat(),
                collection.id,
                collection.collection_id,
            )
            return enricher.run()
        except Exception as exc:
            logger.exception(
                "Card enrichment failed for collection %s: %s",
                collection.collection_id,
                exc,
            )
            return {"enriched": 0, "failed": 0}

    def _refresh_collection_summary(
        self, collection: Collection, progress_callback=None
    ) -> tuple[int, int]:
        from kapsula.infrastructure.repositories.processing.collection_summary_stage import (
            update_collection_library_card,
        )

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
        total = len(missing_docs)
        if total == 0 and progress_callback:
            progress_callback("summarizing", "All documents already summarized", "")
        successes = 0
        failures = 0
        for i, document in enumerate(missing_docs):
            if progress_callback:
                progress_callback(
                    "summarizing",
                    f"Summarizing document {i + 1}/{total}",
                    document.filename,
                )
            try:
                update_collection_library_card(document.id, self._db)
                successes += 1
            except Exception as exc:
                failures += 1
                logger.exception(
                    "Collection maintenance failed to summarize document %s: %s",
                    document.job_id,
                    exc,
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
