"""Element handler protocol.

The concrete ``ContentBlock`` and ``ChunkPipeline`` types live in the
infrastructure layer (they are chunking-engine internals). To keep the
domain layer pure, this Protocol references them only under
``TYPE_CHECKING`` (erased at runtime) and types them as ``Any`` otherwise.
"""

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from kapsula.infrastructure.repositories.chunking.chunk_pipeline import (
        ChunkPipeline,
    )
    from kapsula.infrastructure.repositories.chunking.content_block import (
        ContentBlock,
    )


class ElementHandler(Protocol):
    """Strategy for handling one parsed markdown element during chunking.

    Each handler advances ``ctx.state.i`` past the element(s) it consumed.
    The chunker's main loop also guarantees forward progress (H8), so a
    handler that forgets to advance cannot stall the pipeline.
    """

    def handle(
        self, idx: int, elements: list["ContentBlock"], ctx: "ChunkPipeline"
    ) -> None: ...


# Convenience alias for annotations in code that does not want the
# TYPE_CHECKING quotes (still resolved lazily by type checkers).
ElementList = Any
HandlerContext = Any
