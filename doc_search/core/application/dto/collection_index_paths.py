"""Value object for collection aggregate index paths."""

from __future__ import annotations

import os
from dataclasses import dataclass

_AGGREGATE_FILENAME = "collection_aggregate"


@dataclass(frozen=True)
class CollectionIndexPaths:
    """Resolved paths for a collection's aggregate indexes."""

    indexes_dir: str

    @classmethod
    def from_parts(
        cls,
        data_dir: str,
        account_guid: str | None = None,
        collection_guid: str | None = None,
    ) -> CollectionIndexPaths:
        parts = [p for p in (data_dir, "indexes", account_guid, collection_guid) if p]
        return cls(indexes_dir=os.path.join(*parts))

    @property
    def faiss(self) -> str:
        return os.path.join(self.indexes_dir, f"{_AGGREGATE_FILENAME}_faiss.index")

    @property
    def bm25(self) -> str:
        return os.path.join(self.indexes_dir, f"{_AGGREGATE_FILENAME}_bm25.pkl")

    @property
    def mapping(self) -> str:
        return os.path.join(self.indexes_dir, f"{_AGGREGATE_FILENAME}_mapping.json")

    def exists(self) -> bool:
        return os.path.exists(self.faiss) and os.path.exists(self.bm25)
