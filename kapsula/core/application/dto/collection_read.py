"""Read-model DTO for collections consumed by search use cases."""

from dataclasses import dataclass


@dataclass
class CollectionRead:
    """Read-model projection of a collection for search routing."""

    id: int
    name: str = ""
    collection_id: str = ""
    account_id: int | None = None
    account_guid: str | None = None
