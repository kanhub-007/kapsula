"""Repository interface for document persistence operations.

All parameters and return values use domain entities from
``kapsula.core.domain.entities`` — never ORM models.
"""

from abc import ABC, abstractmethod
from typing import Any

from kapsula.core.domain.entities.document import Document
from kapsula.core.domain.entities.collection import Collection


class DocumentRepository(ABC):
    """Abstracts document and collection persistence."""

    @abstractmethod
    def find_document_by_job_id(self, db: Any, job_id: str) -> Document | None:
        """Return the domain Document with the given job_id, or None."""

    @abstractmethod
    def find_collection_by_guid(self, db: Any, collection_id: str) -> Collection | None:
        """Return the domain Collection with the given GUID, or None."""

    @abstractmethod
    def list_all(self, db: Any) -> list[Document]:
        """Return all documents ordered by creation date descending."""

    @abstractmethod
    def list_by_collection(self, db: Any, collection_guid: str) -> list[Document]:
        """Return documents in a collection ordered by creation date descending."""

    @abstractmethod
    def save_document(self, db: Any, document: Document) -> Document:
        """Persist a new domain Document and return it with the generated identity."""

    @abstractmethod
    def cascade_delete_related(self, db: Any, document: Document) -> int:
        """Delete all chunks, sub-documents, library cards, and structure
        records for the given document.  Returns the number of deleted chunks."""

    @abstractmethod
    def mark_archived(self, db: Any, document: Document) -> None:
        """Mark a document as archived (soft delete) and commit."""
