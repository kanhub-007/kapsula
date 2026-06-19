"""Search within a single document by job_id.

Closes H5: the resolve-doc -> check-completed -> branch subdoc/flat -> search
flow was duplicated across the API ``search_document`` route and the MCP
``search_document`` tool. This use case owns the resolution + readiness
checks and delegates the architecture dispatch to
:meth:`MultiIndexSearcher.search_document`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from kapsula.core.application.dto.search_result_hit import SearchResultHit
from kapsula.core.application.dto.single_document_search import (
    SingleDocumentSearch,
)
from kapsula.core.domain.interfaces.document_repository import DocumentRepository
from kapsula.core.domain.interfaces.session import Session

logger = logging.getLogger(__name__)


class SearchSingleDocumentUseCase:
    """Resolve a document by job_id and search within it."""

    def __init__(
        self,
        document_repository: DocumentRepository,
        make_searcher: Callable[..., object],
    ):
        self._document_repository = document_repository
        self._make_searcher = make_searcher

    async def execute(
        self,
        db: Session,
        job_id: str,
        query: str,
        top_k: int = 10,
        context_mode: str = "none",
        node_type_filter: list[str] | None = None,
    ) -> list[SearchResultHit]:
        """Resolve and search a document.

        Args:
            db: Database session.
            job_id: The job_id (GUID) of the document to search.
            query: Search query text.
            top_k: Maximum results to return.
            context_mode: ``none`` / ``narrow`` / ``deep``.
            node_type_filter: Optional content-type filter.

        Returns:
            Ranked search-result hits.

        Raises:
            ValueError: If the document is missing, not completed, or has no
                searchable indexes.
        """
        doc = self._document_repository.find_document_by_job_id(db, job_id)
        if doc is None:
            raise ValueError(f"Document not found: {job_id}")
        if doc.status != "completed":
            raise ValueError(f"Document not ready. Status: {doc.status}")

        searcher = self._make_searcher()
        return await searcher.search_document(
            SingleDocumentSearch(
                query=query,
                document_id=doc.id,
                faiss_path=doc.faiss_index_path,
                bm25_path=doc.bm25_index_path,
                top_k=top_k,
                context_mode=context_mode,
                node_type_filter=node_type_filter,
            )
        )
