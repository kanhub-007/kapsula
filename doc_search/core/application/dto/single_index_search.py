"""Single-index search parameters."""

from dataclasses import dataclass


@dataclass
class SingleIndexSearch:
    query: str
    faiss_path: str
    bm25_path: str
    document_id: int
    top_k: int = 10
    rerank: bool = False
    context_mode: str = "narrow"
    node_type_filter: list[str] | None = None
