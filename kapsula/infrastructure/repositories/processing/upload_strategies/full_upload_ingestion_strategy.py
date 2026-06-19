"""Full upload ingestion strategy — indexes + summary + aggregate rebuild.

All three pipeline methods are real: document/sub-document indexes are
built, the collection library-card summary is regenerated, and
collection/account aggregate indexes are rebuilt.
"""

from kapsula.infrastructure.logging_config import get_logger
from kapsula.infrastructure.repositories.processing.upload_pipeline_context import (
    UploadPipelineContext,
)

logger = get_logger(__name__)


class FullUploadIngestionStrategy:
    """Builds indexes AND runs all collection maintenance."""

    mode = "full"

    def build_indexes(self, ctx: UploadPipelineContext) -> None:
        """Build FAISS + BM25 indexes (flat or per-sub-document)."""
        from kapsula.infrastructure.repositories.processing.upload_persistence import (
            build_indexes_for_context,
        )

        build_indexes_for_context(ctx)

    def update_collection_summary(self, ctx: UploadPipelineContext) -> None:
        """Regenerate the collection library-card summary via LLM."""
        from kapsula.infrastructure.repositories.processing.collection_summary_stage import (
            update_collection_library_card,
        )
        from kapsula.startup import create_collection_summary_generator

        summary_generator = create_collection_summary_generator()
        update_collection_library_card(
            ctx.document.id, ctx.db, summary_generator=summary_generator
        )

    def rebuild_aggregates(self, ctx: UploadPipelineContext) -> None:
        """Rebuild collection and account aggregate search indexes."""
        from kapsula.infrastructure.repositories.processing.aggregate_build_stage import (
            rebuild_collection_aggregate_index,
        )

        rebuild_collection_aggregate_index(
            ctx.db,
            ctx.document,
            ctx.job_id,
            upload_progress=ctx.progress,
            embedder=ctx.embedder,
            upload_start_time=ctx.start_time,
        )
