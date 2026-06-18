"""Upload ingestion strategy interface.

Each strategy carries **behaviour** (three ctx-taking methods), not boolean
flags. The pipeline calls ``strategy.build_indexes(ctx)`` etc.
unconditionally; each strategy decides whether to act (closes P1).

Methods read everything they need from ``UploadPipelineContext`` —
``ctx.embedder``, ``ctx.progress``, ``ctx.db``, ``ctx.document`` — so
strategies stay stateless and singleton-safe.
"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from kapsula.core.application.dto.upload_pipeline_context import (
        UploadPipelineContext,
    )


class UploadIngestionStrategy(Protocol):
    """Defines per-mode behaviour for the upload pipeline."""

    mode: str

    def build_indexes(self, ctx: "UploadPipelineContext") -> None:
        """Build document/sub-document FAISS+BM25 indexes (no-op for fast)."""
        ...

    def update_collection_summary(self, ctx: "UploadPipelineContext") -> None:
        """Regenerate the collection library-card summary (no-op for fast/indexed)."""
        ...

    def rebuild_aggregates(self, ctx: "UploadPipelineContext") -> None:
        """Rebuild collection/account aggregate indexes (no-op for fast/indexed)."""
        ...
