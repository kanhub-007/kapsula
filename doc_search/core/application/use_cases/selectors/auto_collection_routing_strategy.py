"""Auto collection routing strategy with ambiguity detection."""

from __future__ import annotations

from doc_search.core.application.use_cases.selectors.collection_routing_strategy import (
    _annotate_collection,
)
from doc_search.core.application.use_cases.selectors.fast_collection_routing_strategy import (
    FastCollectionRoutingStrategy,
)
from doc_search.core.application.use_cases.selectors.llm_collection_routing_strategy import (
    LlmCollectionRoutingStrategy,
)
from doc_search.core.application.use_cases.selectors.metadata_preselector import (
    MetadataPreselector,
)
from doc_search.core.domain.interfaces.chat_client import ChatClient


class AutoCollectionRoutingStrategy:
    """Default routing strategy.

    Uses the cheap strategy for trivial candidate sets and LLM routing
    when a real decision is required. When multiple candidates exist, a
    metadata preselection step checks whether one candidate is clearly
    dominant — if so, LLM routing is skipped.
    """

    _AMBIGUITY_THRESHOLD = 0.9

    def __init__(self, chat_client: ChatClient):
        self._fast = FastCollectionRoutingStrategy()
        self._llm = LlmCollectionRoutingStrategy(chat_client)
        self._preselector = MetadataPreselector(max_candidates=10, min_candidates=2)

    def select(self, query: str, collections: list[dict]) -> list[dict]:
        if len(collections) <= 1:
            return self._fast.select(query, collections)

        preselected = self._preselector.select(query, collections)
        if self._is_unambiguous(preselected):
            top = preselected[: len(collections)]
            return [
                _annotate_collection(
                    candidate,
                    candidate.get("metadata_route_confidence", 0.85),
                    reason="Auto: unambiguous metadata routing",
                )
                for candidate in top
            ]

        return self._llm.select(query, collections)

    @classmethod
    def _is_unambiguous(cls, preselected: list[dict]) -> bool:
        if len(preselected) < 2:
            return True
        first = preselected[0].get("metadata_score", 0.0)
        second = preselected[1].get("metadata_score", 0.0)
        if first <= 0:
            return False
        return (first - second) / max(first, 1e-6) >= cls._AMBIGUITY_THRESHOLD
