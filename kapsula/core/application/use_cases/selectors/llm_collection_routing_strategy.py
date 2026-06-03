"""LLM-based collection routing strategy."""

from __future__ import annotations

from kapsula.core.application.use_cases.selectors.collection_routing_strategy import (
    _annotate_collection,
)
from kapsula.core.application.use_cases.selectors.collection_selector import (
    CollectionSelector,
)
from kapsula.core.domain.interfaces.chat_client import ChatClient


class LlmCollectionRoutingStrategy:
    """Use the LLM-backed collection selector."""

    def __init__(self, chat_client: ChatClient):
        self._selector = CollectionSelector(chat_client)

    def select(self, query: str, collections: list[dict]) -> list[dict]:
        selected_ids = self._selector.select(query, collections)
        if not selected_ids:
            return [
                _annotate_collection(coll, 0.8, reason="LLM selected all (fallback)")
                for coll in collections
            ]
        selected = [coll for coll in collections if coll["id"] in selected_ids]
        reason = (
            "LLM selected subset"
            if len(selected_ids) < len(collections)
            else "LLM selected all"
        )
        confidence = 0.9 if len(selected_ids) < len(collections) else 0.7
        return [
            _annotate_collection(coll, confidence, reason=reason) for coll in selected
        ]
