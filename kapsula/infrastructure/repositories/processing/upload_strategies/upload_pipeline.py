"""UploadPipeline — Template Method orchestrator for document processing.

Runs five ordered steps (spec S2.1):
    extract_structure → chunk_and_persist → build_indexes →
    finalize_document → run_maintenance

``run()`` is a flat dispatcher; each ``_step`` is a private method under
50 lines. Chunking is delegated to a :class:`ChunkingStrategy`; indexing
and maintenance are delegated to an :class:`UploadIngestionStrategy`.

The pipeline owns no session lifecycle — it receives ``ctx.db`` and the
presentation adapter (``tasks.py``) is responsible for closing it.
"""

from __future__ import annotations

import time

from kapsula.core.domain.interfaces.chunking_strategy import (
    ChunkingStrategy,
)
from kapsula.core.domain.interfaces.upload_ingestion_strategy import (
    UploadIngestionStrategy,
)
from kapsula.infrastructure.data import DocumentStructure, LibraryCard
from kapsula.infrastructure.logging_config import get_logger
from kapsula.infrastructure.repositories.chunking import (
    extract_document_structure_skeleton,
)
from kapsula.infrastructure.repositories.processing._chunk_linker import (
    _link_chunks_to_parents,
)
from kapsula.infrastructure.repositories.processing.upload_pipeline_context import (
    UploadPipelineContext,
)

logger = get_logger(__name__)


class UploadPipeline:
    """Orchestrates the five-step document upload pipeline."""

    def __init__(
        self,
        chunking: ChunkingStrategy,
        ingestion: UploadIngestionStrategy,
    ):
        self._chunking = chunking
        self._ingestion = ingestion

    def run(self, ctx: UploadPipelineContext) -> None:
        """Execute the full pipeline. Flat dispatcher — one line per step."""
        self._extract_structure(ctx)
        self._chunk_and_persist(ctx)
        self._build_indexes(ctx)
        self._finalize_document(ctx)
        self._run_maintenance(ctx)

    # ── steps ────────────────────────────────────────────────────────

    def _extract_structure(self, ctx: UploadPipelineContext) -> None:
        """Extract the heading skeleton and persist a DocumentStructure row."""
        ctx.progress.set(
            job_id=ctx.job_id,
            status="processing",
            progress=10,
            stage="extracting_structure",
            message="Extracting document structure...",
            ingestion_mode=ctx.ingestion_mode,
        )
        skeleton = extract_document_structure_skeleton(ctx.markdown_content)
        ctx.db.add(
            DocumentStructure(document_id=ctx.document.id, skeleton_structure=skeleton)
        )
        ctx.db.commit()
        ctx.structure = skeleton
        logger.info("Job %s: Skeleton structure extracted", ctx.job_id)

    def _chunk_and_persist(self, ctx: UploadPipelineContext) -> None:
        """Chunk (via strategy) then persist chunks + cards + subdocuments."""
        ctx.progress.set(
            job_id=ctx.job_id,
            status="processing",
            progress=30,
            stage="chunking",
            message="Creating chunks...",
            ingestion_mode=ctx.ingestion_mode,
        )
        self._chunking.extract_and_chunk(ctx)
        if ctx.subdoc_plan:
            from kapsula.infrastructure.repositories.processing.upload_persistence import (
                persist_subdocuments,
            )

            persist_subdocuments(ctx.db, ctx.document, ctx.subdoc_plan)
        else:
            from kapsula.infrastructure.repositories.processing.upload_persistence import (
                persist_flat_chunks,
            )

            persist_flat_chunks(ctx.db, ctx.document, ctx.chunks, ctx.parent_sections)
            _link_chunks_to_parents(
                ctx.job_id,
                ctx.document,
                ctx.parent_sections,
                ctx.db,
                _progress_store(ctx),
            )
        logger.info("Job %s: Persisted %d chunks", ctx.job_id, len(ctx.chunks))

    def _build_indexes(self, ctx: UploadPipelineContext) -> None:
        """Delegate index building to the ingestion strategy."""
        self._ingestion.build_indexes(ctx)

    def _finalize_document(self, ctx: UploadPipelineContext) -> None:
        """Mark the document completed and create the document LibraryCard."""
        ctx.duration = time.time() - ctx.start_time
        ctx.document.status = "completed"
        ctx.document.duration = ctx.duration
        ctx.db.commit()
        if ctx.subdoc_plan:
            _create_document_card(ctx)
        logger.info("Job %s: Processing completed in %.2fs", ctx.job_id, ctx.duration)

    def _run_maintenance(self, ctx: UploadPipelineContext) -> None:
        """Run collection summary + aggregate maintenance via the strategy."""
        self._ingestion.update_collection_summary(ctx)
        self._ingestion.rebuild_aggregates(ctx)


# ── module-level helpers (keep step methods under 50 lines) ──────────


def _progress_store(ctx: UploadPipelineContext):
    """Return the legacy dict store used by ``_link_chunks_to_parents``.

    The context's progress tracker is the source of truth; the legacy flat
    linker writes ``processing_status[job_id]`` directly, so we expose the
    same backing dict to keep both in sync until the linker is ported to
    the tracker interface.
    """
    from kapsula.infrastructure.repositories.processing.upload_progress_store import (
        processing_status,
    )

    return processing_status


def _create_document_card(ctx: UploadPipelineContext) -> None:
    """Create the main document LibraryCard for the subdocument path."""
    subdoc_summary = {
        entry["breadcrumb_key"]: len(entry["pages"]) for entry in ctx.subdoc_plan
    }
    total_pages = sum(subdoc_summary.values())
    ctx.db.add(
        LibraryCard(
            collection_id=ctx.document.collection_id,
            document_id=ctx.document.id,
            doc_id=f"main_{ctx.document.id}",
            level="document",
            title="Document Overview",
            content=(
                f"Contains {len(ctx.subdoc_plan)} sub-documents with "
                f"{total_pages} total pages"
            ),
        )
    )
    ctx.db.commit()
