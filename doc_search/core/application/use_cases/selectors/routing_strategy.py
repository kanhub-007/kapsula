"""Routing strategy implementations for collection selection."""

from __future__ import annotations

from typing import Protocol

from doc_search.core.application.use_cases.selectors.collection_selector import (
    CollectionSelector,
)
from doc_search.core.domain.interfaces.chat_client import ChatClient


class CollectionRoutingStrategy(Protocol):
    """Strategy interface for selecting collection metadata rows."""

    def select(self, query: str, collections: list[dict]) -> list[dict]:
        """Return the collection metadata rows to search."""
        ...


class LlmCollectionRoutingStrategy:
    """Use the LLM-backed collection selector."""

    def __init__(self, chat_client: ChatClient):
        self._selector = CollectionSelector(chat_client)

    def select(self, query: str, collections: list[dict]) -> list[dict]:
        selected_ids = self._selector.select(query, collections)
        return [coll for coll in collections if coll["id"] in selected_ids]


class FastCollectionRoutingStrategy:
    """Cheap routing strategy that avoids LLM calls.

    This initial implementation preserves recall by searching all collection
    candidates already allowed by the scope. It is intentionally conservative
    until the metadata pre-router phase is implemented.
    """

    def select(self, query: str, collections: list[dict]) -> list[dict]:
        return collections


class AutoCollectionRoutingStrategy:
    """Default routing strategy.

    Uses the cheap strategy for trivial candidate sets and LLM routing when a
    real decision is required.
    """

    def __init__(self, chat_client: ChatClient):
        self._fast = FastCollectionRoutingStrategy()
        self._llm = LlmCollectionRoutingStrategy(chat_client)

    def select(self, query: str, collections: list[dict]) -> list[dict]:
        if len(collections) <= 1:
            return self._fast.select(query, collections)
        return self._llm.select(query, collections)


def make_collection_routing_strategy(
    routing_mode: str,
    chat_client: ChatClient,
) -> CollectionRoutingStrategy:
    """Create the routing strategy requested by a search DTO."""
    normalized = (routing_mode or "auto").strip().lower()
    if normalized == "fast":
        return FastCollectionRoutingStrategy()
    if normalized == "llm":
        return LlmCollectionRoutingStrategy(chat_client)
    return AutoCollectionRoutingStrategy(chat_client)
