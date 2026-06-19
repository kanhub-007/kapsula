"""Table element strategy."""

from kapsula.infrastructure.repositories.chunking.chunk_pipeline import ChunkPipeline
from kapsula.infrastructure.repositories.chunking.content_block import ContentBlock

from ..table_parser import transform_table_to_text


class TableHandler:
    """Emits a table as an atomic chunk, transforming its HTML (when present)
    into a readable text form first."""

    def handle(
        self, idx: int, elements: list[ContentBlock], ctx: ChunkPipeline
    ) -> None:
        element = elements[idx]
        state = ctx.state
        ctx.flush()

        text = (
            transform_table_to_text(element.html) if element.html else element.content
        )
        fused_text = _with_next_if_small(elements, idx, text, ctx.tk)
        fused_next = fused_text != text

        ctx.add_atomic(fused_text, "table")
        state.chunk_start_header = state.current_header
        if fused_next:
            # Only advance past the fused element when fusion actually
            # happened. Previously this compared fused_text to
            # element.content, which is also True for HTML-transformed
            # tables — and then wrongly skipped the next element (latent
            # bug closed here alongside L3).
            state.i = idx + 2


def _with_next_if_small(
    elements: list[ContentBlock], idx: int, text: str, count_tokens
) -> str:
    if idx + 1 < len(elements):
        nxt = elements[idx + 1]
        if nxt.type in ("text",):
            if count_tokens(nxt.content) < 100:
                return f"{text}\n\n{nxt.content}"
    return text
