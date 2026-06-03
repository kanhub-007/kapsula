"""Collection search strategy protocol."""

from __future__ import annotations

from typing import Protocol


class CollectionSearchStrategy(Protocol):
    """Strategy for searching a single collection.

    Implementations choose between aggregate indexes, per-document
    iteration, or future approaches.  Returning ``None`` means the
    strategy could not handle the request and the caller should fall
    through to the next strategy.
    """

    async def search(
        self,
        collection: dict,
        query: str,
        top_k: int,
        per_document_multiplier: int,
        rerank: bool,
        context_mode: str,
        node_type_filter: list[str] | None,
    ) -> list[dict] | None: ...
