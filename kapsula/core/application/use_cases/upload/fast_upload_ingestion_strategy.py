"""Fast upload ingestion strategy — parse, chunk, persist, no indexes.

All three pipeline methods are no-ops: no embedding, no aggregate rebuild,
no collection summary regeneration. The caller still marks maintenance
state stale and increments the upload counter so deferred maintenance
picks the document up later.
"""

from kapsula.core.application.dto.upload_pipeline_context import (
    UploadPipelineContext,
)


class FastUploadIngestionStrategy:
    """No indexes, no maintenance — just records."""

    mode = "fast"

    def build_indexes(self, ctx: UploadPipelineContext) -> None:
        """No-op: fast mode skips all index building."""

    def update_collection_summary(self, ctx: UploadPipelineContext) -> None:
        """No-op: fast mode skips collection summary regeneration."""

    def rebuild_aggregates(self, ctx: UploadPipelineContext) -> None:
        """No-op: fast mode skips aggregate index rebuilds.

        Maintenance state (mark-stale + increment-uploads) is handled by the
        pipeline's maintenance step, not by this strategy — it runs for
        every mode.
        """
