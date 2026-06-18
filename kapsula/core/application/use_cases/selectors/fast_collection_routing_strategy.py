"""Fast (metadata-only) collection routing strategy."""

from __future__ import annotations

from kapsula.core.application.use_cases.selectors.collection_routing_strategy import (
    annotate_collection,
)


class FastCollectionRoutingStrategy:
    """Cheap routing strategy that avoids LLM calls.

    Preserves recall by searching all collection candidates already allowed
    by the scope. Assigns moderate confidence since no LLM validation is
    performed.
    """

    def select(self, query: str, collections: list[dict]) -> list[dict]:
        return [
            annotate_collection(coll, 0.8, reason="Fast routing (all candidates)")
            for coll in collections
        ]
