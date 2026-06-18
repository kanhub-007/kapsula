"""Indexed upload ingestion strategy — builds document/subdoc indexes.

``build_indexes`` is real (FAISS + BM25 per document / sub-document);
``update_collection_summary`` and ``rebuild_aggregates`` are no-ops
(collection maintenance is deferred).
"""

from kapsula.core.application.dto.upload_pipeline_context import (
    UploadPipelineContext,
)
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class IndexedUploadIngestionStrategy:
    """Builds document indexes; defers collection maintenance."""

    mode = "indexed"

    def build_indexes(self, ctx: UploadPipelineContext) -> None:
        """Build FAISS + BM25 indexes for the document (flat path).

        Sub-document indexes are built by the sub-document chunking strategy
        in Slice 3; this method handles the flat-document case.
        """
        from kapsula.infrastructure.repositories.processing._chunk_linker import (
            _build_document_indexes,
        )

        _build_document_indexes(
            ctx.job_id,
            ctx.document,
            ctx.chunks,
            ctx.db,
            ctx.ingestion_mode,
            ctx.progress,
            embedder=ctx.embedder,
        )

    def update_collection_summary(self, ctx: UploadPipelineContext) -> None:
        """No-op: indexed mode defers collection summary regeneration."""

    def rebuild_aggregates(self, ctx: UploadPipelineContext) -> None:
        """No-op: indexed mode defers aggregate index rebuilds."""
