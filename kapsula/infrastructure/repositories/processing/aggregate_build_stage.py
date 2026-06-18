"""Rebuild collection and account aggregate search indexes.

Extracted from ``presentation/api/tasks.py``.
"""

import time

from sqlalchemy.orm import Session

from kapsula.infrastructure.data.connection import DATA_DIR
from kapsula.infrastructure.data.tables.chunk import Chunk
from kapsula.infrastructure.data.tables.collection import Collection as OrmCollection
from kapsula.infrastructure.data.tables.document import Document as OrmDocument
from kapsula.infrastructure.repositories.indexing.aggregate_index_builder import AggregateIndexBuilder
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


def rebuild_collection_aggregate_index(
    db: Session,
    document: OrmDocument,
    job_id: str,
    *,
    upload_progress,
    embedder,
    upload_start_time: float | None = None,
) -> None:
    """Rebuild collection/account aggregate indexes after a full ingestion.

    Args:
        db: Database session.
        document: The ORM document whose collection's aggregates need rebuilding.
        job_id: Upload job ID for progress tracking.
        upload_progress: ``UploadProgressTracker`` instance for progress updates.
        embedder: An ``Embedder`` instance for building FAISS indexes.
        upload_start_time: Timestamp when the upload started (for elapsed messages).
    """
    try:
        collection = document.collection
        if not collection:
            return

        account = collection.account
        account_guid = account.account_id if account else None

        builder = AggregateIndexBuilder(embedder, DATA_DIR)

        completed_collection_chunks = (
            db.query(Chunk)
            .join(OrmDocument, Chunk.document_id == OrmDocument.id)
            .filter(
                OrmDocument.collection_id == collection.id,
                OrmDocument.status == "completed",
            )
            .count()
        )
        collection_stage_start = time.time()
        upload_progress.set(
            job_id,
            status="processing",
            progress=90,
            stage="collection_aggregate_index",
            message=(
                f"Rebuilding collection aggregate index: {completed_collection_chunks} chunks "
                f"from collection '{collection.name}' "
                f"({upload_progress.elapsed_message(upload_start_time or collection_stage_start)})."
            ),
        )
        builder.build(
            db,
            collection_id=collection.id,
            account_id=account_guid,
            collection_guid=collection.collection_id,
        )
        upload_progress.log_stage(
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
            completed_account_chunks = (
                db.query(Chunk)
                .join(OrmDocument, Chunk.document_id == OrmDocument.id)
                .join(OrmCollection, OrmDocument.collection_id == OrmCollection.id)
                .filter(
                    OrmCollection.account_id == account.id,
                    OrmDocument.status == "completed",
                )
                .count()
            )
            account_stage_start = time.time()
            upload_progress.set(
                job_id,
                status="processing",
                progress=95,
                stage="account_aggregate_index",
                message=(
                    f"Rebuilding account aggregate index: {completed_account_chunks} chunks "
                    f"for account '{account.name}' "
                    f"({upload_progress.elapsed_message(upload_start_time or account_stage_start)})."
                ),
            )
            builder.build_account(
                db,
                account_id=account.id,
                account_guid=account.account_id,
            )
            upload_progress.log_stage(
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

        upload_progress.set(
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
        upload_progress.set(
            job_id,
            status="processing",
            progress=98,
            stage="finalizing",
            message=(
                "Aggregate maintenance failed but document indexing is complete; "
                "finalizing upload."
            ),
        )
