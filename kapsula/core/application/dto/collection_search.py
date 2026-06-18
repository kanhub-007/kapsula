"""Collection search parameters."""

from dataclasses import dataclass

from kapsula.core.application.dto.search_scope import SearchScope


@dataclass
class CollectionSearch:
    query: str
    account_id: str | None = None
    collection_id: str | None = None
    top_k: int = 10
    context_mode: str = "narrow"
    per_document_multiplier: int = 2
    node_type_filter: list[str] | None = None
    routing_mode: str = "auto"
    max_subdocument_candidates_for_llm: int = 30
    min_subdocument_candidates: int = 5

    @property
    def scope(self) -> SearchScope:
        """Return an explicit value object for the intended search scope."""
        return SearchScope.from_ids(
            account_id=self.account_id,
            collection_id=self.collection_id,
        )
