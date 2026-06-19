"""Upload ingestion strategy interface.

Each strategy carries **behaviour** (three ctx-taking methods), not boolean
flags. The pipeline calls ``strategy.build_indexes(ctx)`` etc.
unconditionally; each strategy decides whether to act (closes P1).

Methods read everything they need from the pipeline context —
``ctx.embedder``, ``ctx.progress``, ``ctx.db``, ``ctx.document`` — so
strategies stay stateless and singleton-safe.

The concrete context lives in the infrastructure layer; it is typed
structurally here to keep the domain layer pure.
"""

from typing import Any, Protocol


class UploadIngestionStrategy(Protocol):
    """Defines per-mode behaviour for the upload pipeline."""

    mode: str

    def build_indexes(self, ctx: Any) -> None:
        """Build document/sub-document FAISS+BM25 indexes (no-op for fast)."""
        ...

    def update_collection_summary(self, ctx: Any) -> None:
        """Regenerate the collection library-card summary (no-op for fast/indexed)."""
        ...

    def rebuild_aggregates(self, ctx: Any) -> None:
        """Rebuild collection/account aggregate indexes (no-op for fast/indexed)."""
        ...
