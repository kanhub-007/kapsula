"""Read-only library-card query repository interface."""

from abc import ABC, abstractmethod
from typing import Any

from kapsula.core.domain.entities.library_card import LibraryCard


class LibraryCardRepository(ABC):
    """Read-only queries for library cards."""

    @abstractmethod
    def find_collection_card(self, db: Any, collection_id: int) -> LibraryCard | None:
        """Return the collection-level library card, or None."""

    @abstractmethod
    def count_by_document(self, db: Any, document_id: int) -> int:
        """Return count of library cards for a document."""
