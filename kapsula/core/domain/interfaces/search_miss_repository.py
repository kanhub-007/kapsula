"""Repository interface for persisting search-miss log entries."""

from abc import ABC, abstractmethod


class SearchMissLogRepository(ABC):
    """Persists searches that returned few/no results, for gap detection."""

    @abstractmethod
    def log(
        self,
        collection_id: str,
        query: str,
        result_count: int,
        top_score: float,
    ) -> None:
        """Persist a single search-miss observation.

        Args:
            collection_id: Collection GUID the search was scoped to.
            query: The user's query text (will be truncated by the impl).
            result_count: Number of results returned.
            top_score: Highest score among the results, or 0.0 if none.
        """
