"""Search scope kind enum."""

from enum import Enum


class SearchScopeKind(str, Enum):
    """Supported collection-search scopes."""

    GLOBAL = "global"
    ACCOUNT = "account"
    COLLECTION = "collection"
