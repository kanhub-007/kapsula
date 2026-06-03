"""Source quota policy for preventing result pollution during ranking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SourceQuotaPolicy:
    """Apply per-source limits before final top-k selection.

    Prevents a single source from flooding the final result set.
    Results are sorted by score before quotas are applied.
    """

    per_collection_limit: int | None = None
    per_document_limit: int | None = None
    per_subdocument_limit: int = 3

    def apply(self, results: list[dict], top_k: int) -> list[dict]:
        """Return results with quotas applied, preserving overflow.

        Preferred results (within quotas) come first, followed by
        overflow for backup selection.
        """
        if not results:
            return []

        collection_limit = self.per_collection_limit or max(top_k, top_k * 3)
        document_limit = self.per_document_limit or max(3, top_k // 2)

        kept: list[dict] = []
        overflow: list[dict] = []
        collection_counts: dict[Any, int] = {}
        document_counts: dict[Any, int] = {}
        subdocument_counts: dict[Any, int] = {}

        for result in results:
            if _exceeds_limits(
                result,
                collection_counts,
                document_counts,
                subdocument_counts,
                collection_limit,
                document_limit,
                self.per_subdocument_limit,
            ):
                overflow.append(result)
                continue
            kept.append(result)
            _increment_counts(
                result, collection_counts, document_counts, subdocument_counts
            )

        if len(kept) < top_k:
            needed = top_k - len(kept)
            kept.extend(overflow[:needed])
            overflow = overflow[needed:]

        return kept + overflow

    def select(self, results: list[dict], top_k: int) -> list[dict]:
        """Return a strictly constrained top-k candidate list.

        Unlike ``apply``, this does not preserve overflow.
        """
        return self.apply(results, top_k)[:top_k]


def _exceeds_limits(
    result: dict,
    collection_counts: dict[Any, int],
    document_counts: dict[Any, int],
    subdocument_counts: dict[Any, int],
    collection_limit: int,
    document_limit: int,
    subdocument_limit: int,
) -> bool:
    return (
        collection_counts.get(result.get("collection_id"), 0) >= collection_limit
        or document_counts.get(result.get("document_id"), 0) >= document_limit
        or (
            result.get("sub_document_id") is not None
            and subdocument_counts.get(result.get("sub_document_id"), 0)
            >= subdocument_limit
        )
    )


def _increment_counts(
    result: dict,
    collection_counts: dict[Any, int],
    document_counts: dict[Any, int],
    subdocument_counts: dict[Any, int],
) -> None:
    for key, counts in [
        ("collection_id", collection_counts),
        ("document_id", document_counts),
    ]:
        value = result.get(key)
        if value is not None:
            counts[value] = counts.get(value, 0) + 1
    subdoc_id = result.get("sub_document_id")
    if subdoc_id is not None:
        subdocument_counts[subdoc_id] = subdocument_counts.get(subdoc_id, 0) + 1
