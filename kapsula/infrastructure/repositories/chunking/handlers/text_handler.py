"""Text element strategy."""

from kapsula.infrastructure.repositories.chunking.chunk_pipeline import ChunkPipeline
from kapsula.infrastructure.repositories.chunking.content_block import ContentBlock


class TextHandler:
    """Accumulates text elements into the current chunk, flushing first if the
    new content would exceed the token budget."""

    def handle(
        self, idx: int, elements: list[ContentBlock], ctx: ChunkPipeline
    ) -> None:
        element = elements[idx]
        state = ctx.state
        token_count = ctx.tk(element.content)

        if state.current_tokens + token_count > ctx.max_tokens:
            ctx.flush()

        ctx.append(element.content)
        state.i = idx + 1
