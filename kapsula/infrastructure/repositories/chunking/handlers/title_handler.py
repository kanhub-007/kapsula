"""Title element strategy."""

from kapsula.infrastructure.repositories.chunking.chunk_pipeline import ChunkPipeline
from kapsula.infrastructure.repositories.chunking.content_block import ContentBlock


class TitleHandler:
    """Updates the heading breadcrumb stack on a title element, flushing the
    current chunk when the heading is H3 or above (level <= 3)."""

    def handle(
        self, idx: int, elements: list[ContentBlock], ctx: ChunkPipeline
    ) -> None:
        element = elements[idx]
        state = ctx.state

        if element.level <= 3:
            ctx.flush()

        while state.header_stack and state.header_stack[-1][0] >= element.level:
            state.header_stack.pop()
        state.header_stack.append((element.level, element.content))
        state.current_header = " > ".join(h[1] for h in state.header_stack)
        state.i = idx + 1
