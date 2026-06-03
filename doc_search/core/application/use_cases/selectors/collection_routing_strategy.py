"""Protocol and factory for collection routing strategies."""

from __future__ import annotations

from typing import Protocol

from doc_search.core.domain.interfaces.chat_client import ChatClient


class CollectionRoutingStrategy(Protocol):
    """Strategy interface for selecting collection metadata rows."""

    def select(self, query: str, collections: list[dict]) -> list[dict]:
        """Return the collection metadata rows to search.

        Each returned row is annotated with ``collection_route_confidence``
        and optionally ``collection_route_reason``.
        """
        ...


def _annotate_collection(collection: dict, confidence: float, reason: str = "") -> dict:
    annotated = dict(collection)
    annotated["collection_route_confidence"] = confidence
    if reason:
        annotated["collection_route_reason"] = reason
    return annotated


def make_collection_routing_strategy(
    routing_mode: str,
    chat_client: ChatClient,
) -> CollectionRoutingStrategy:
    """Create the routing strategy requested by a search DTO."""
    from doc_search.core.application.use_cases.selectors.auto_collection_routing_strategy import (
        AutoCollectionRoutingStrategy,
    )
    from doc_search.core.application.use_cases.selectors.fast_collection_routing_strategy import (
        FastCollectionRoutingStrategy,
    )
    from doc_search.core.application.use_cases.selectors.llm_collection_routing_strategy import (
        LlmCollectionRoutingStrategy,
    )

    normalized = (routing_mode or "auto").strip().lower()
    if normalized == "fast":
        return FastCollectionRoutingStrategy()
    if normalized == "llm":
        return LlmCollectionRoutingStrategy(chat_client)
    return AutoCollectionRoutingStrategy(chat_client)
