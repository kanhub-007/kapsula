"""Tests for ConsolidationRunner — Classical school, in-memory repository.

Black-box: exercises the documented contract now that all DB access is
delegated to ConsolidationCardRepository. Uses an in-memory fake
repository and a FakeChatClient. Asserts on the run result and on the
cards the repository recorded — never on chat_client interactions.
"""

from dataclasses import dataclass
from typing import Any

from kapsula.core.domain.interfaces.chat_client import ChatClient
from kapsula.core.domain.interfaces.consolidation_card_repository import (
    ConsolidationCardRepository,
)
from kapsula.infrastructure.repositories.processing.consolidation_runner import (
    ConsolidationRunner,
)


class FakeChatClient(ChatClient):
    """Returns canned JSON responses from a FIFO queue."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)

    def send(self, messages, max_tokens=500, temperature=0.3) -> str:
        return self._responses.pop(0) if self._responses else "{}"


@dataclass
class _FakeCard:
    id: int
    title: str
    content: str
    level: str = "level_2"
    card_type: str = "extractive"
    document: Any = None


@dataclass
class _FakeMiss:
    query: str
    result_count: int
    top_score: float


class InMemoryConsolidationCardRepository(ConsolidationCardRepository):
    """Records every call; returns canned data for reads."""

    def __init__(
        self,
        cards: list[_FakeCard] | None = None,
        misses: list[_FakeMiss] | None = None,
    ):
        self._cards_in = list(cards or [])
        self._misses = list(misses or [])
        self.topic_cards_created: list[dict] = []
        self.topic_cards_updated: list[dict] = []
        self.evolution_cards: list[str] = []
        self.gap_cards: list[list[dict]] = []
        self.runs_recorded: list[dict] = []
        self._has_previous = False
        self._previous_labels: set[str] = set()

    def fetch_extractive_cards(self, collection_id):
        return list(self._cards_in)

    def fetch_existing_topic_labels(self, collection_id):
        return [t["label"] for t in self.topic_cards_created] + [
            t["label"] for t in self.topic_cards_updated
        ]

    def upsert_topic_card(
        self,
        collection_id,
        run_id,
        label,
        summary,
        importance,
        source_card_ids,
        contradictions=None,
    ) -> tuple[str, int]:
        existing_labels = {t["label"] for t in self.topic_cards_created}
        record = {
            "label": label,
            "summary": summary,
            "importance": importance,
            "source_ids": source_card_ids,
            "contradictions": contradictions,
        }
        if label in existing_labels:
            self.topic_cards_updated.append(record)
            return "updated", len(self.topic_cards_created) + 1
        self.topic_cards_created.append(record)
        return "created", len(self.topic_cards_created)

    def upsert_evolution_card(self, collection_id, run_id, content) -> None:
        self.evolution_cards.append(content)

    def fetch_previous_topic_labels(self, collection_id):
        return set(self._previous_labels)

    def has_previous_run(self, collection_guid, run_id):
        return self._has_previous

    def add_gap_cards(self, collection_id, run_id, gaps) -> int:
        self.gap_cards.append(gaps)
        return len(gaps)

    def fetch_search_misses(self, collection_guid, limit=100):
        return list(self._misses)[:limit]

    def record_run(
        self,
        run_id,
        collection_guid,
        cards_created,
        cards_updated,
        conflicts_found,
        gaps_found,
        error,
    ):
        self.runs_recorded.append(
            {
                "run_id": run_id,
                "cards_created": cards_created,
                "cards_updated": cards_updated,
                "conflicts_found": conflicts_found,
                "gaps_found": gaps_found,
                "error": error,
            }
        )


def _runner(repo, responses):
    return ConsolidationRunner(
        card_repository=repo,
        chat_client=FakeChatClient(responses),
        collection_id=1,
        collection_guid="coll-guid-1",
    )


class TestConsolidationRunner:
    def test_no_extractive_cards_records_empty_run(self):
        repo = InMemoryConsolidationCardRepository(cards=[])

        result = _runner(repo, responses=[]).run()

        assert result["cards_created"] == 0
        assert len(repo.runs_recorded) == 1
        assert repo.runs_recorded[0]["error"] is None
        # No topic cards written.
        assert repo.topic_cards_created == []

    def test_topic_clustering_creates_topic_cards(self):
        cards = [
            _FakeCard(id=1, title="Banking", content="about banks", level="level_2"),
            _FakeCard(
                id=2, title="Clearing", content="about clearing", level="level_2"
            ),
        ]
        repo = InMemoryConsolidationCardRepository(cards=cards)
        cluster_response = (
            '{"topics": [{"label": "BIS Clearinghouse", '
            '"card_ids": [0, 1], "rationale": "both about banking"}]}'
        )
        topic_response = (
            '{"summary": "Synthesis of banking and clearing.", '
            '"importance": 0.9, "contradictions": []}'
        )

        result = _runner(repo, [cluster_response, topic_response]).run()

        assert result["cards_created"] >= 1
        assert len(repo.topic_cards_created) == 1
        assert repo.topic_cards_created[0]["label"] == "BIS Clearinghouse"
        assert repo.topic_cards_created[0]["importance"] == 0.9
        # Source cards linked.
        assert repo.topic_cards_created[0]["source_ids"] == [1, 2]

    def test_importance_clamped_to_unit_interval(self):
        cards = [_FakeCard(id=1, title="T", content="c", level="level_2")]
        repo = InMemoryConsolidationCardRepository(cards=cards)
        cluster_response = '{"topics": [{"label": "T", "card_ids": [0]}]}'
        # LLM returns importance > 1.0; runner must clamp.
        topic_response = '{"summary": "s", "importance": 5.0, "contradictions": []}'

        _runner(repo, [cluster_response, topic_response]).run()

        assert repo.topic_cards_created[0]["importance"] == 1.0

    def test_failing_topic_card_does_not_abort_run(self):
        cards = [
            _FakeCard(id=1, title="A", content="a", level="level_2"),
            _FakeCard(id=2, title="B", content="b", level="level_2"),
        ]
        repo = InMemoryConsolidationCardRepository(cards=cards)
        # Two clusters; the first topic response is malformed JSON (no summary),
        # the second is valid. Both must be attempted.
        cluster_response = (
            '{"topics": [{"label": "A", "card_ids": [0]}, '
            '{"label": "B", "card_ids": [1]}]}'
        )
        topic_response_a = '{"importance": 0.5, "contradictions": []}'
        topic_response_b = '{"summary": "b summary", "importance": 0.5}'

        result = _runner(
            repo, [cluster_response, topic_response_a, topic_response_b]
        ).run()

        # Run completed despite the malformed first card; at least one created.
        assert len(repo.runs_recorded) == 1
        assert repo.runs_recorded[0]["error"] is None
        assert result["cards_created"] + result["cards_updated"] >= 1

    def test_record_run_persists_on_top_level_failure(self):
        """If the whole run blows up, record_run still fires with the error."""

        class _ExplodingRepo(InMemoryConsolidationCardRepository):
            def fetch_extractive_cards(self, collection_id):
                raise RuntimeError("DB down")

        repo = _ExplodingRepo()
        result = _runner(repo, []).run()

        assert len(repo.runs_recorded) == 1
        assert "DB down" in repo.runs_recorded[0]["error"]
        assert result["cards_created"] == 0
