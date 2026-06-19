"""Chunking strategy interface.

Each strategy populates the upload pipeline context with chunks (and, for
the subdocument variant, a per-subdocument plan) WITHOUT touching the
database — persistence is the pipeline step's job. This keeps strategies
pure and unit-testable.

The concrete ``UploadPipelineContext`` lives in the infrastructure layer
(it carries ORM-bound handles), so the context parameter is typed
structurally here to keep the domain layer pure (no infrastructure import,
not even under ``TYPE_CHECKING``).
"""

from typing import Any, Protocol


class ChunkingStrategy(Protocol):
    """Splits markdown into chunks and populates the pipeline context."""

    def extract_and_chunk(self, ctx: Any) -> None:
        """Populate ctx.chunks / ctx.parent_sections (and ctx.subdoc_plan
        for the subdocument variant). No database access."""
        ...
