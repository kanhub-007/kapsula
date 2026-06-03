"""Repository interface for document persistence operations.

All parameters and return values use domain entities from
``doc_search.core.domain.entities`` — never ORM models.
"""

from abc import ABC, abstractmethod

from doc_search.core.domain.entities.document import Document
from doc_search.core.domain.entities.collection import Collection


class DocumentRepository(ABC):
    """Abstracts document and collection persistence."""

    @abstractmethod
    def find_document_by_job_id(self, db, job_id: str) -> Document | None:
        """Return the domain Document with the given job_id, or None."""

    @abstractmethod
    def find_collection_by_guid(self, db, collection_id: str) -> Collection | None:
        """Return the domain Collection with the given GUID, or None."""

    @abstractmethod
    def list_all(self, db) -> list[Document]:
        """Return all documents ordered by creation date descending."""

    @abstractmethod
    def list_by_collection(self, db, collection_guid: str) -> list[Document]:
        """Return documents in a collection ordered by creation date descending."""

    @abstractmethod
    def save_document(self, db, document: Document) -> None:
        """Persist a new domain Document and flush its identity."""

    @abstractmethod
    def cascade_delete_related(self, db, document: Document) -> int:
        """Delete all chunks, sub-documents, library cards, and structure
        records for the given document.  Returns the number of deleted chunks."""

    @abstractmethod
    def mark_archived(self, db, document: Document) -> None:
        """Mark a document as archived (soft delete) and commit."""
