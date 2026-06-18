"""Sub-document search parameters."""

from dataclasses import dataclass


@dataclass
class SubDocumentSearch:
    query: str
    document_id: int
    top_k: int = 10
    context_mode: str = "narrow"
    per_subdoc_multiplier: int = 3
    node_type_filter: list[str] | None = None
