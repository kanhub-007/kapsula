"""Search scope value object.

Represents the intended breadth of a search without relying on ambiguous
combinations of optional IDs throughout the application layer.
"""

from dataclasses import dataclass
from enum import Enum


class SearchScopeKind(str, Enum):
    """Supported collection-search scopes."""

    GLOBAL = "global"
    ACCOUNT = "account"
    COLLECTION = "collection"


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
