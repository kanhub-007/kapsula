"""Chunking pipeline — accumulates text, flushes chunks, handles token limits."""

from .chunk_state import ChunkState
from .markdown_utils import count_tokens


class ChunkPipeline:
    """Manages the chunk accumulation and flushing pipeline.

    Strategies call :meth:`append` to add text and :meth:`flush` to
    finalize the current chunk.  Atomic elements (tables, code) use
    :meth:`add_atomic`, which handles its own sizing.
    """

    def __init__(
        self,
        max_tokens: int,
        hard_limit: int,
        encoding_name: str,
        state: ChunkState,
    ):
        self.max_tokens = max_tokens
        self.hard_limit = hard_limit
        self.state = state
        self._encoding = encoding_name

    # -- token counting --------------------------------------------------

    def tk(self, text: str) -> int:
        return count_tokens(text, self._encoding)

    # -- accumulation ----------------------------------------------------

    def append(self, text: str) -> None:
        s = self.state
        if not s.current:
            s.chunk_start_header = s.current_header
        s.current.append(text)
        s.current_tokens = self.tk("\n\n".join(s.current))

    def flush(self) -> None:
        s = self.state
        if not s.current:
            return
        content = "\n\n".join(s.current)
        s.new_chunk()
        if self.tk(content) > self.max_tokens:
            for part in self._split_large(content):
                s.chunks.append(self._make_chunk(part))
                s.chunk_index += 1
        else:
            s.chunks.append(self._make_chunk(content))
            s.chunk_index += 1

    def add_atomic(self, content: str, node_type: str) -> None:
        s = self.state
        if self.tk(content) > self.hard_limit:
            for part in self._split_large(content):
                s.chunks.append(self._make_chunk(part, node_type))
                s.chunk_index += 1
        else:
            s.chunks.append(self._make_chunk(content, node_type))
            s.chunk_index += 1

    def add_parts(self, content: str) -> None:
        s = self.state
        for part in self._split_large(content):
            s.chunks.append(self._make_chunk(part))
            s.chunk_index += 1

    # -- internal --------------------------------------------------------

    def _make_chunk(self, content: str, node_type: str = "text") -> dict:
        s = self.state
        return {
            "content": content,
            "token_count": self.tk(content),
            "metadata": {
                "chunk_index": s.chunk_index,
                "header": s.chunk_start_header or "No header",
                "node_type": node_type,
                "parents": {},
            },
        }

    def _split_large(self, content: str) -> list[str]:
        paragraphs = content.split("\n\n")
        parts = []
        current_part = []
        current_tokens = 0
        for para in paragraphs:
            pt = self.tk(para)
            if current_tokens + pt > self.max_tokens and current_part:
                parts.append("\n\n".join(current_part))
                current_part = [para]
                current_tokens = pt
            else:
                current_part.append(para)
                current_tokens += pt
        if current_part:
            parts.append("\n\n".join(current_part))
        return parts
