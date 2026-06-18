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

    # ── backward-compat bridges (removed in Slice 2 when tasks.py is rewritten) ─
    @property
    def build_document_indexes(self) -> bool:
        return True

    @property
    def rebuild_aggregate_indexes(self) -> bool:
        return False

    def build_indexes(self, ctx: UploadPipelineContext) -> None:
        """Build FAISS + BM25 indexes (flat or per-sub-document)."""
        from kapsula.infrastructure.repositories.processing.upload_persistence import (
            build_indexes_for_context,
        )

        build_indexes_for_context(ctx)

    def update_collection_summary(self, ctx: UploadPipelineContext) -> None:
        """No-op: indexed mode defers collection summary regeneration."""

    def rebuild_aggregates(self, ctx: UploadPipelineContext) -> None:
        """No-op rebuild, but mark the collection stale so deferred
        maintenance picks it up (preserves the old mark-stale behaviour)."""
        from kapsula.infrastructure.repositories.processing.upload_persistence import (
            mark_deferred_maintenance,
        )

        mark_deferred_maintenance(ctx, summary=False)
