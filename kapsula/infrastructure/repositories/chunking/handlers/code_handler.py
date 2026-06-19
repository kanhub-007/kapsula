"""Code element strategy."""

from kapsula.infrastructure.repositories.chunking.chunk_pipeline import ChunkPipeline
from kapsula.infrastructure.repositories.chunking.content_block import ContentBlock


class CodeHandler:
    """Emits a code block as an atomic chunk, optionally fusing a small
    following text element so tiny trailing comments are not orphaned."""

    def handle(
        self, idx: int, elements: list[ContentBlock], ctx: ChunkPipeline
    ) -> None:
        element = elements[idx]
        state = ctx.state

        if state.current:
            ctx.flush()

        text = _with_next_if_small(elements, idx, element.content, ctx.tk)
        if text != element.content:
            idx += 1

        ctx.add_atomic(text, "code")
        state.chunk_start_header = state.current_header
        state.i = idx + 1


def _with_next_if_small(
    elements: list[ContentBlock], idx: int, text: str, count_tokens
) -> str:
    if idx + 1 < len(elements):
        nxt = elements[idx + 1]
        if nxt.type in ("text",):
            if count_tokens(nxt.content) < 100:
                return f"{text}\n\n{nxt.content}"
    return text
