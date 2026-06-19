"""Read-only chunk query repository interface."""

from abc import ABC, abstractmethod
from typing import Any

from kapsula.core.domain.entities.chunk import Chunk


class ChunkRepository(ABC):
    """Read-only queries for document chunks."""

    @abstractmethod
    def list_by_document(self, db: Any, document_id: int) -> list[Chunk]:
        """Return all chunks for a document, ordered by chunk_index."""

    @abstractmethod
    def count_by_document(self, db: Any, document_id: int) -> int:
        """Return the number of chunks for a document."""
