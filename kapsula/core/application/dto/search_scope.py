"""Search scope value object.

Represents the intended breadth of a search without relying on ambiguous
combinations of optional IDs throughout the application layer.
"""

from dataclasses import dataclass

from kapsula.core.application.dto.search_scope_kind import SearchScopeKind


@dataclass(frozen=True)
class SearchScope:
    """Value object describing where a collection search should run."""

    kind: SearchScopeKind
    account_id: str | None = None
    collection_id: str | None = None

    @classmethod
    def from_ids(
        cls,
        account_id: str | None = None,
        collection_id: str | None = None,
    ) -> "SearchScope":
        """Create a scope from external IDs.

        Collection scope is the narrowest and therefore wins when both IDs are
        present. Presentation adapters should normally avoid passing both, but
        this keeps application behavior deterministic.
        """
        if collection_id:
            return cls(SearchScopeKind.COLLECTION, collection_id=collection_id)
        if account_id:
            return cls(SearchScopeKind.ACCOUNT, account_id=account_id)
        return cls(SearchScopeKind.GLOBAL)
