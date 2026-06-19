"""Read-only sub-document query repository interface."""

from abc import ABC, abstractmethod
from typing import Any

from kapsula.core.domain.entities.sub_document import SubDocument


class SubDocumentRepository(ABC):
    """Read-only queries for sub-documents."""

    @abstractmethod
    def list_by_document(self, db: Any, document_id: int) -> list[SubDocument]:
        """Return all sub-documents for a document."""
