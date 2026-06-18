"""Search scope kind enum."""

from enum import StrEnum


class SearchScopeKind(StrEnum):
    """Supported collection-search scopes."""

    GLOBAL = "global"
    ACCOUNT = "account"
    COLLECTION = "collection"
