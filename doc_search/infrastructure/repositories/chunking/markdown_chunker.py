"""Markdown chunking with type-based strategy dispatch."""

from typing import List, Dict, Any

from doc_search.core.domain.interfaces.chunker import Chunker
from .chunk_state import ChunkState
from .chunk_pipeline import ChunkPipeline
from .markdown_parser import MarkdownParser
from .handlers import HandlerRegistry
from doc_search.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class MarkdownChunker(Chunker):
    """Chunks markdown content into token-bounded segments.

    Uses a :class:`HandlerRegistry` to dispatch each element to the
    correct handler.
    """

    def __init__(
        self,
        max_tokens: int = 512,
        hard_limit: int = 800,
        encoding_name: str = "cl100k_base",
        parser: MarkdownParser | None = None,
        registry: HandlerRegistry | None = None,
    ):
        self._max_tokens = max_tokens
        self._hard_limit = hard_limit
        self._encoding = encoding_name
        self._parser = parser or MarkdownParser()
        self._registry = registry or HandlerRegistry()

    def chunk(self, content: str) -> List[Dict[str, Any]]:
        elements = self._parser.parse(content)

        state = ChunkState()
        pipe = ChunkPipeline(self._max_tokens, self._hard_limit, self._encoding, state)

        state.i = 0
        while state.i < len(elements):
            el = elements[state.i]
            handler = self._registry.get(el.type)
            handler.handle(state.i, elements, pipe)

        pipe.flush()
        logger.info(f"Chunking complete: {len(state.chunks)} chunks")
        return state.chunks
