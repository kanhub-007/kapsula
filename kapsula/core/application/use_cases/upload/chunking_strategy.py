"""Chunking strategy interface.

Each strategy populates ``UploadPipelineContext`` with chunks (and, for the
subdocument variant, a per-subdocument plan) WITHOUT touching the database —
persistence is the pipeline step's job. This keeps strategies pure and
unit-testable.

Closes the flat-vs-subdocument Strategy selection (spec S2.3): the pipeline
holds one ChunkingStrategy and calls ``extract_and_chunk(ctx)``; the
SubDocument variant falls back to Flat composition when no valid
breadcrumbs are found.
"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from kapsula.core.application.dto.upload_pipeline_context import (
        UploadPipelineContext,
    )


class ChunkingStrategy(Protocol):
    """Splits markdown into chunks and populates the pipeline context."""

    def extract_and_chunk(self, ctx: "UploadPipelineContext") -> None:
        """Populate ctx.chunks / ctx.parent_sections (and ctx.subdoc_plan
        for the subdocument variant). No database access."""
        ...
