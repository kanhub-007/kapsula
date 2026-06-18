"""Domain value object for aggregate index rebuild results."""

from dataclasses import dataclass


@dataclass
class RebuildResult:
    """Result of rebuilding collection and account aggregate indexes."""

    collection_faiss: str | None = None
    collection_bm25: str | None = None
    account_faiss: str | None = None
    account_bm25: str | None = None
