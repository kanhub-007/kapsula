"""Sub-document (Russian Doll) chunking strategy.

Splits markdown on breadcrumb H1 headers into sub-documents, chunks each,
and populates ``ctx.subdoc_plan`` (one entry per sub-document carrying its
breadcrumb_key, pages, chunks, and parent_sections).

Falls back to a held :class:`FlatChunkingStrategy` when no valid
sub-documents are found (spec S2.3) — so the pipeline runs one skeleton
regardless of document shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kapsula.core.application.dto.upload_pipeline_context import (
    UploadPipelineContext,
)
from kapsula.core.domain.services.citation_linker import (
    add_citation_metadata_to_chunks,
)
from kapsula.infrastructure.logging_config import get_logger
from kapsula.infrastructure.repositories.chunking import extract_parent_sections
from kapsula.infrastructure.repositories.chunking.breadcrumb_parser import (
    extract_subdocuments,
    validate_subdocuments,
)

logger = get_logger(__name__)


if TYPE_CHECKING:
    from kapsula.core.application.use_cases.upload.flat_chunking_strategy import (
        FlatChunkingStrategy,
    )


class SubDocumentChunkingStrategy:
    """Chunks per sub-document, with flat fallback."""

    def __init__(self, flat: FlatChunkingStrategy | None = None):
        # Lazy import to avoid a circular dependency at module load.
        if flat is None:
            from kapsula.core.application.use_cases.upload.flat_chunking_strategy import (
                FlatChunkingStrategy,
            )

            flat = FlatChunkingStrategy()
        self._flat = flat

    def extract_and_chunk(self, ctx: UploadPipelineContext) -> None:
        """Populate ctx.chunks + ctx.subdoc_plan, or fall back to flat."""
        subdocs = extract_subdocuments(ctx.markdown_content)

        if not validate_subdocuments(subdocs):
            logger.warning(
                "Job %s: No valid sub-documents found, falling back to flat "
                "chunking",
                ctx.job_id,
            )
            self._flat.extract_and_chunk(ctx)
            return

        logger.info("Job %s: Found %d sub-documents", ctx.job_id, len(subdocs))

        plan: list[dict] = []
        all_chunks: list[dict] = []
        for breadcrumb_key, pages in subdocs.items():
            subdoc_content = "\n\n".join(page["content"] for page in pages)
            parent_sections = extract_parent_sections(subdoc_content)
            chunks = ctx.chunker.chunk(subdoc_content)
            chunks = add_citation_metadata_to_chunks(
                chunks=chunks,
                parent_sections=parent_sections,
                markdown_content=subdoc_content,
            )
            plan.append(
                {
                    "breadcrumb_key": breadcrumb_key,
                    "pages": pages,
                    "chunks": chunks,
                    "parent_sections": parent_sections,
                }
            )
            all_chunks.extend(chunks)

        ctx.subdoc_plan = plan
        ctx.chunks = all_chunks
        logger.info(
            "Job %s: Chunked %d sub-documents into %d total chunks",
            ctx.job_id,
            len(plan),
            len(all_chunks),
        )
