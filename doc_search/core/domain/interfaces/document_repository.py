"""Repository interface for document persistence operations."""

from abc import ABC, abstractmethod
from typing import Any


class DocumentRepository(ABC):
    """Abstracts document and collection persistence behind an interface
    so use cases never touch ORM models directly."""

    @abstractmethod
    def find_document_by_job_id(self, db, job_id: str) -> Any | None:
        """Return the document with the given job_id, or None."""

    @abstractmethod
    def find_collection_by_guid(self, db, collection_id: str) -> Any | None:
        """Return the collection with the given GUID, or None."""

    @abstractmethod
    def save_document(self, db, document: Any) -> None:
        """Persist a new document record and flush its identity."""

    @abstractmethod
    def cascade_delete_related(self, db, document: Any) -> int:
        """Delete all chunks, sub-documents, library cards, and structure
        records for the given document.  Returns the number of deleted chunks."""

    @abstractmethod
    def mark_archived(self, db, document: Any) -> None:
        """Mark a document as archived (soft delete) and commit."""
