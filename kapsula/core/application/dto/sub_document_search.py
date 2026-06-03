"""Sub-document search parameters."""

from dataclasses import dataclass


@dataclass
class SubDocumentSearch:
    query: str
    document_id: int
    top_k: int = 10
    rerank: bool = False
    context_mode: str = "narrow"
    hf_api_token: str | None = None
    per_subdoc_multiplier: int = 3
    node_type_filter: list[str] | None = None
