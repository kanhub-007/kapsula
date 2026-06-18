"""Search data access interface — all DB queries needed by use cases.

All methods return application read-models (DTOs) or plain primitives,
never ORM instances. This keeps the application layer decoupled from
SQLAlchemy (closes the ORM-leak finding A1). Account persistence lives
on :class:`AccountRepository` instead (ISP — closes S1).
"""

from typing import Protocol

from kapsula.core.application.dto.collection_read import CollectionRead
from kapsula.core.application.dto.document_read import DocumentRead
from kapsula.core.application.dto.sub_document_read import SubDocumentRead


class _LibraryCardRead(Protocol):
    """Minimal shape of a library card read by the metadata builder."""

    content: str
    extra_metadata: str | None


class SearchDataAccess(Protocol):
    """Interface for document search data access."""

    def get_sub_documents(self, document_id: int) -> list[SubDocumentRead]: ...

    def get_completed_documents(self, collection_id: int) -> list[DocumentRead]: ...

    def get_collections_by_account(self, account_id: str) -> list[CollectionRead]: ...

    def get_collection_by_collection_id(
        self, collection_id: str
    ) -> CollectionRead | None: ...

    def get_all_collections(self) -> list[CollectionRead]: ...

    def get_collection_library_card(
        self, collection_id: int
    ) -> _LibraryCardRead | None: ...

    def get_library_card_for_sub_doc(
        self, sub_doc_id: int
    ) -> _LibraryCardRead | None: ...

    def get_library_card_by_doc_id(
        self, doc_id: str, sub_doc_id: int | None = None
    ) -> _LibraryCardRead | None: ...

    def get_chunk(
        self, document_id: int, chunk_index: int, sub_doc_id: int | None = None
    ): ...

    def get_chunks_batch(
        self, document_id: int, chunk_specs: list[tuple[int, int | None]]
    ) -> dict: ...

    def get_library_cards_by_doc_ids(self, doc_ids: list[str]) -> dict: ...

    def count_sub_documents(self, document_id: int) -> int: ...
