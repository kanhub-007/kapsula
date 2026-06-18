"""Flat chunking strategy — chunks the whole document as one unit.

Populates ``ctx.chunks`` (with citation metadata) and
``ctx.parent_sections``. Leaves ``ctx.subdoc_plan`` as ``None`` so the
persistence step knows to use the flat path.
"""

from kapsula.core.application.dto.upload_pipeline_context import (
    UploadPipelineContext,
)
from kapsula.core.domain.services.citation_linker import (
    add_citation_metadata_to_chunks,
)
from kapsula.infrastructure.logging_config import get_logger
from kapsula.infrastructure.repositories.chunking import extract_parent_sections

logger = get_logger(__name__)


class FlatChunkingStrategy:
    """Chunks markdown content as a single document."""

    def extract_and_chunk(self, ctx: UploadPipelineContext) -> None:
        """Populate ctx.chunks + ctx.parent_sections from the full document."""
        parent_sections = extract_parent_sections(ctx.markdown_content)
        ctx.parent_sections = parent_sections
        logger.info(
            "Job %s: Extracted %d parent sections (flat)",
            ctx.job_id,
            len(parent_sections),
        )

        chunks = ctx.chunker.chunk(ctx.markdown_content)
        ctx.chunks = add_citation_metadata_to_chunks(
            chunks=chunks,
            parent_sections=parent_sections,
            markdown_content=ctx.markdown_content,
        )
        logger.info("Job %s: Created %d chunks (flat)", ctx.job_id, len(ctx.chunks))
