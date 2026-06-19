"""Background task adapter for document processing.

Thin adapter (spec S2.2): builds an ``UploadPipelineContext`` + pipeline
via ``startup/`` and calls ``pipeline.run()``. All chunking, persistence,
indexing, and maintenance live in the pipeline (application layer) and its
helpers. This file performs no direct database operations — it only
constructs the context and owns the session lifecycle + error handling.
"""

import time

from sqlalchemy.orm import Session

from kapsula.core.domain.entities.upload_ingestion_mode import UploadIngestionMode
from kapsula.infrastructure.logging_config import get_logger
from kapsula.infrastructure.repositories.chunking import MarkdownChunker
from kapsula.infrastructure.repositories.data.sql_upload_job_repository import (
    SqlUploadJobRepository,
)
from kapsula.infrastructure.repositories.processing.upload_persistence import (
    load_document_by_job_id,
    mark_document_failed,
)
from kapsula.infrastructure.repositories.processing.upload_pipeline_context import (
    UploadPipelineContext,
)
from kapsula.infrastructure.repositories.processing.upload_progress_store import (
    processing_status,
)
from kapsula.infrastructure.repositories.processing.upload_progress_tracker import (
    UploadProgressTracker,
)
from kapsula.startup import (
    create_embedder,
    create_maintenance_state_manager,
    create_upload_pipeline,
)

logger = get_logger(__name__)

# Shared progress tracker + job manager (singletons for the process).
_upload_progress = UploadProgressTracker(processing_status, logger)
_upload_job_manager = SqlUploadJobRepository()
_maintenance_state = create_maintenance_state_manager()


def process_document_with_subdocuments(
    job_id: str,
    markdown_content: str,
    max_tokens: int,
    db: Session,
    ingestion_mode: str = "indexed",
):
    """Process a document end-to-end via the upload pipeline.

    Args:
        job_id: Unique job identifier (GUID).
        markdown_content: Raw markdown content to process.
        max_tokens: Maximum tokens per chunk.
        db: Database session (closed in ``finally``).
        ingestion_mode: fast | indexed | full.
    """
    pipeline, ingestion = create_upload_pipeline(ingestion_mode)
    mode = UploadIngestionMode.normalize(ingestion_mode)
    logger.info(
        "Starting pipeline processing for job %s ingestion_mode=%s", job_id, mode
    )
    start_time = time.time()

    try:
        document = load_document_by_job_id(db, job_id)

        ctx = UploadPipelineContext(
            db=db,
            document=document,
            job_id=job_id,
            ingestion_mode=mode,
            start_time=start_time,
            markdown_content=markdown_content,
            chunker=MarkdownChunker(max_tokens=max_tokens),
            embedder=create_embedder(),
            progress=_upload_progress,
            maintenance_state=_maintenance_state,
            card_repo=None,
            chunk_repo=None,
        )

        pipeline.run(ctx)

        _finalize_progress(ctx)
    except Exception as exc:
        mark_document_failed(
            db,
            job_id,
            f"Job {job_id}: Processing failed: {exc}",
            processing_status,
            _upload_job_manager,
        )
    finally:
        db.close()


def get_processing_status(job_id: str) -> dict:
    """Return the current processing status for a job, or None."""
    return _upload_progress.get(job_id)


# ── internals ────────────────────────────────────────────────────────


def _finalize_progress(ctx: UploadPipelineContext) -> None:
    """Emit the terminal completed progress + job-row update."""
    chunk_count = len(ctx.chunks)
    subdocument_count = len(ctx.subdoc_plan) if ctx.subdoc_plan else None
    extra = {"subdocument_count": subdocument_count} if subdocument_count else {}
    _upload_progress.set(
        ctx.job_id,
        status="completed",
        progress=100,
        stage="completed",
        message=(
            f"Processing completed successfully. Created {chunk_count} chunks "
            f"in {ctx.duration:.2f} seconds."
        ),
        chunk_count=chunk_count,
        duration=ctx.duration,
        ingestion_mode=ctx.ingestion_mode,
        **extra,
    )
    _upload_job_manager.update(
        ctx.job_id,
        status="completed",
        progress=100,
        stage="completed",
        chunk_count=chunk_count,
        duration=ctx.duration,
        **extra,
    )
