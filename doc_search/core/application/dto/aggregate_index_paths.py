"""Value object for aggregate index file paths (collection and account scope)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AggregateIndexPaths:
    """Resolved paths for aggregate FAISS, BM25, and chunk mapping files."""

    indexes_dir: str
    filename_prefix: str

    @classmethod
    def for_collection(
        cls,
        data_dir: str,
        account_guid: str | None = None,
        collection_guid: str | None = None,
    ) -> AggregateIndexPaths:
        parts = [p for p in (data_dir, "indexes", account_guid, collection_guid) if p]
        return cls(
            indexes_dir=os.path.join(*parts), filename_prefix="collection_aggregate"
        )

    @classmethod
    def for_account(
        cls,
        data_dir: str,
        account_guid: str,
    ) -> AggregateIndexPaths:
        return cls(
            indexes_dir=os.path.join(data_dir, "indexes", account_guid),
            filename_prefix="account_aggregate",
        )

    @property
    def faiss(self) -> str:
        return os.path.join(self.indexes_dir, f"{self.filename_prefix}_faiss.index")

    @property
    def bm25(self) -> str:
        return os.path.join(self.indexes_dir, f"{self.filename_prefix}_bm25.pkl")

    @property
    def mapping(self) -> str:
        return os.path.join(self.indexes_dir, f"{self.filename_prefix}_mapping.json")

    @property
    def faiss_npy(self) -> str:
        return os.path.join(self.indexes_dir, f"{self.filename_prefix}_faiss.index.npy")

    def exists(self) -> bool:
        return os.path.exists(self.faiss) and os.path.exists(self.bm25)
