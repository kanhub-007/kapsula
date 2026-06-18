"""Rebuild collection and account aggregate search indexes."""

import os
import time

from sqlalchemy.orm import Session

from kapsula.infrastructure.data.tables.collection import Collection
from kapsula.infrastructure.data.tables.document import Document
from kapsula.infrastructure.data.connection import DATA_DIR
from kapsula.infrastructure.repositories.indexing.aggregate_index_builder import AggregateIndexBuilder
from kapsula.infrastructure.repositories.embedding.huggingface_embedder import HuggingFaceEmbedder
from kapsula.presentation.upload.maintenance_state_manager import MaintenanceStateManager
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


def _rebuild_collection_aggregate_index(
    db: Session,
    document: Document,
    job_id: str,
    upload_start_time: float | None = None,
) -> None:
    """Rebuild collection/account aggregate indexes after a full ingestion."""
    global _embedder_singleton
    try:
        from kapsula.infrastructure.repositories.indexing.aggregate_index_builder import (
            AggregateIndexBuilder,
        )

        collection = document.collection
        if not collection:
            return

        account = collection.account
        account_guid = account.account_id if account else None

        if _embedder_singleton is None:
            from kapsula.startup import create_embedder

            _embedder_singleton = create_embedder()

        builder = AggregateIndexBuilder(_embedder_singleton, DATA_DIR)

        completed_collection_chunks = (
            db.query(Chunk)
            .join(Document, Chunk.document_id == Document.id)
            .filter(
                Document.collection_id == collection.id,
                Document.status == "completed",
            )
            .count()
        )
        collection_stage_start = time.time()
        _upload_progress.set(
            job_id,
            status="processing",
            progress=90,
            stage="collection_aggregate_index",
            message=(
                f"Rebuilding collection aggregate index: {completed_collection_chunks} chunks "
                f"from collection '{collection.name}' "
                f"({_upload_progress.elapsed_message(upload_start_time or collection_stage_start)})."
            ),
        )
        builder.build(
            db,
            collection_id=collection.id,
            account_id=account_guid,
            collection_guid=collection.collection_id,
        )
        _upload_progress.log_stage(
            job_id,
            "aggregate_collection",
            collection_stage_start,
            chunks=completed_collection_chunks,
            collection_id=collection.collection_id,
        )
        logger.info(
            "Job %s: Collection aggregate index rebuilt for collection '%s'",
            job_id,
            collection.name,
        )

        if account:
            from kapsula.infrastructure.data.tables.collection import (
                Collection as CollectionTable,
            )

            completed_account_chunks = (
                db.query(Chunk)
                .join(Document, Chunk.document_id == Document.id)
                .join(CollectionTable, Document.collection_id == CollectionTable.id)
                .filter(
                    CollectionTable.account_id == account.id,
                    Document.status == "completed",
                )
                .count()
            )
            account_stage_start = time.time()
            _upload_progress.set(
                job_id,
                status="processing",
                progress=95,
                stage="account_aggregate_index",
                message=(
                    f"Rebuilding account aggregate index: {completed_account_chunks} chunks "
                    f"for account '{account.name}' "
                    f"({_upload_progress.elapsed_message(upload_start_time or account_stage_start)})."
                ),
            )
            builder.build_account(
                db,
                account_id=account.id,
                account_guid=account.account_id,
            )
            _upload_progress.log_stage(
                job_id,
                "aggregate_account",
                account_stage_start,
                chunks=completed_account_chunks,
                account_id=account.account_id,
            )
            logger.info(
                "Job %s: Account aggregate index rebuilt for account '%s'",
                job_id,
                account.name,
            )

        _upload_progress.set(
            job_id,
            status="processing",
            progress=98,
            stage="finalizing",
            message="Aggregate maintenance finished; finalizing upload.",
        )
    except Exception as exc:
        logger.error(
            "Job %s: Failed to rebuild aggregate index: %s",
            job_id,
            exc,
        )
        _upload_progress.set(
            job_id,
            status="processing",
            progress=98,
            stage="finalizing",
            message=(
                "Aggregate maintenance failed but document indexing is complete; "
                "finalizing upload."
            ),
        )


