"""Repository interface for consolidation card persistence.

Closes A2/S4: ConsolidationRunner must not perform ``session.add`` /
``session.query`` inline. All writes go through this repository so the
runner becomes pure orchestration and is unit-testable with an
in-memory fake.
"""

from abc import ABC, abstractmethod
from typing import Any


class ConsolidationCardRepository(ABC):
    """Read + write access for the cards and runs touched by consolidation."""

    @abstractmethod
    def fetch_extractive_cards(self, collection_id: int) -> list[Any]:
        """Return all H2/H3 extractive cards for the collection (detached)."""

    @abstractmethod
    def fetch_existing_topic_labels(self, collection_id: int) -> list[str]:
        """Return existing topic card labels for the collection (dedup hint)."""

    @abstractmethod
    def upsert_topic_card(
        self,
        collection_id: int,
        run_id: str,
        label: str,
        summary: str,
        importance: float,
        source_card_ids: list[int],
        contradictions: list[dict] | None = None,
    ) -> tuple[str, int]:
        """Insert or update a topic card and link it to its sources.

        Returns ``(status, card_id)`` where status is ``"created"`` or
        ``"updated"``.
        """

    @abstractmethod
    def upsert_evolution_card(
        self, collection_id: int, run_id: str, content: str
    ) -> None:
        """Insert or update the single evolution card for the collection."""

    @abstractmethod
    def fetch_previous_topic_labels(self, collection_id: int) -> set[str]:
        """Return topic labels from before this run (for evolution diffing)."""

    @abstractmethod
    def has_previous_run(self, collection_guid: str, run_id: str) -> bool:
        """Return True if a prior consolidation run exists for the collection."""

    @abstractmethod
    def add_gap_cards(self, collection_id: int, run_id: str, gaps: list[dict]) -> int:
        """Insert gap cards. Returns the count inserted."""

    @abstractmethod
    def fetch_search_misses(self, collection_guid: str, limit: int = 100) -> list[Any]:
        """Return recent search-miss rows for gap analysis."""

    @abstractmethod
    def record_run(
        self,
        run_id: str,
        collection_guid: str,
        cards_created: int,
        cards_updated: int,
        conflicts_found: int,
        gaps_found: int,
        error: str | None,
    ) -> None:
        """Persist the consolidation_run row."""
