"""Single-document search parameters (unified subdoc + flat dispatch)."""

from dataclasses import dataclass


@dataclass
class SingleDocumentSearch:
    """Parameters for searching within one resolved document.

    Carries the document's index paths so :meth:`MultiIndexSearcher.search_document`
    can dispatch to the sub-document or flat path without the caller knowing
    which architecture the document uses.
    """

    query: str
    document_id: int
    faiss_path: str | None = None
    bm25_path: str | None = None
    top_k: int = 10
    context_mode: str = "none"
    node_type_filter: list[str] | None = None
