"""Collection search parameters."""

from dataclasses import dataclass


@dataclass
class CollectionSearch:
    query: str
    account_id: str
    top_k: int = 10
    rerank: bool = False
    context_mode: str = "narrow"
    hf_api_token: str | None = None
    per_document_multiplier: int = 2
