"""Repository interfaces for read-model queries (chunks, cards, subdocs, jobs)."""

from abc import ABC, abstractmethod
from typing import Any

from kapsula.core.domain.entities.chunk import Chunk
from kapsula.core.domain.entities.library_card import LibraryCard
from kapsula.core.domain.entities.sub_document import SubDocument


class ChunkRepository(ABC):
    """Read-only queries for document chunks."""

    @abstractmethod
    def list_by_document(self, db: Any, document_id: int) -> list[Chunk]:
        """Return all chunks for a document, ordered by chunk_index."""

    @abstractmethod
    def count_by_document(self, db: Any, document_id: int) -> int:
        """Return the number of chunks for a document."""


class SubDocumentRepository(ABC):
    """Read-only queries for sub-documents."""

    @abstractmethod
    def list_by_document(self, db: Any, document_id: int) -> list[SubDocument]:
        """Return all sub-documents for a document."""


class LibraryCardRepository(ABC):
    """Read-only queries for library cards."""

    @abstractmethod
    def find_collection_card(self, db: Any, collection_id: int) -> LibraryCard | None:
        """Return the collection-level library card, or None."""

    @abstractmethod
    def count_by_document(self, db: Any, document_id: int) -> int:
        """Return count of library cards for a document."""
