"""Mutable state tracked during chunking."""

from dataclasses import dataclass, field


@dataclass
class ChunkState:
    chunks: list = field(default_factory=list)
    current: list[str] = field(default_factory=list)
    current_tokens: int = 0
    current_header: str = ""
    header_stack: list = field(default_factory=list)
    chunk_start_header: str = ""
    chunk_index: int = 0
    i: int = 0

    def new_chunk(self):
        self.current.clear()
        self.current_tokens = 0
