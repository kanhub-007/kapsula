"""Repository interface for Collection persistence."""

from abc import ABC, abstractmethod
from typing import Any

from kapsula.core.domain.entities.collection import Collection


class CollectionRepository(ABC):
    """Persistence for collections."""

    @abstractmethod
    def list_all(self, db: Any) -> list[Collection]:
        """Return all collections ordered by creation date descending."""

    @abstractmethod
    def list_by_account(self, db: Any, account_id: str) -> list[Collection]:
        """Return collections belonging to a specific account."""

    @abstractmethod
    def find_by_collection_id(self, db: Any, collection_id: str) -> Collection | None:
        """Return the collection with the given GUID, or None."""

    @abstractmethod
    def find_by_id(self, db: Any, internal_id: int) -> Collection | None:
        """Return the collection with the given internal ID, or None."""

    @abstractmethod
    def save(self, db: Any, collection: Collection) -> Collection:
        """Persist a new collection and return it with the generated identity."""
