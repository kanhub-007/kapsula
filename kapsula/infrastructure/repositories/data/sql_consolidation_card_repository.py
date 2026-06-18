"""SQLAlchemy-backed ConsolidationCardRepository.

Owns every DB read/write that ConsolidationRunner previously performed
inline. Each method opens a short transaction so SQLite write locks are
held only for the brief write, never across long LLM calls (per the
``short-lived-write-transactions`` spec).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, joinedload

from kapsula.core.domain.interfaces.consolidation_card_repository import (
    ConsolidationCardRepository,
)
from kapsula.infrastructure.data import (
    CardReference,
    ConsolidationRun,
    LibraryCard,
    SearchMissLog,
)
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class SqlConsolidationCardRepository(ConsolidationCardRepository):
    """SQL implementation of consolidation card persistence."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _short_session(self) -> Session:
        """Open a fresh session. Caller MUST close."""
        return self._session_factory()

    def fetch_extractive_cards(self, collection_id: int) -> list[Any]:
        session = self._short_session()
        try:
            cards = (
                session.query(LibraryCard)
                .options(joinedload(LibraryCard.document))
                .filter(
                    LibraryCard.collection_id == collection_id,
                    LibraryCard.card_type == "extractive",
                    LibraryCard.level.in_(["level_2", "level_3"]),
                )
                .order_by(LibraryCard.title)
                .all()
            )
            for card in cards:
                session.expunge(card)
            return cards
        finally:
            session.close()

    def fetch_existing_topic_labels(self, collection_id: int) -> list[str]:
        session = self._short_session()
        try:
            rows = (
                session.query(LibraryCard.title)
                .filter(
                    LibraryCard.collection_id == collection_id,
                    LibraryCard.card_type == "topic",
                )
                .all()
            )
            return [r[0] for r in rows if r[0]]
        finally:
            session.close()

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
        import json

        session = self._short_session()
        try:
            existing = (
                session.query(LibraryCard)
                .filter(
                    LibraryCard.collection_id == collection_id,
                    LibraryCard.card_type == "topic",
                    LibraryCard.title == label,
                )
                .first()
            )

            if existing:
                existing.content = summary
                existing.importance = importance
                existing.updated_at = datetime.now(UTC)
                existing.consolidation_run_id = run_id
                card = existing
                status = "updated"
            else:
                card = LibraryCard(
                    collection_id=collection_id,
                    doc_id=str(uuid.uuid4()),
                    level="topic",
                    title=label,
                    content=summary,
                    card_type="topic",
                    importance=importance,
                    consolidation_run_id=run_id,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                session.add(card)
                session.flush()
                status = "created"

            for source_id in source_card_ids:
                session.add(
                    CardReference(
                        source_card_id=card.id,
                        target_card_id=source_id,
                        relation_type="synthesizes_from",
                    )
                )

            if contradictions:
                card.extra_metadata = json.dumps({"contradictions": contradictions})

            session.commit()
            return status, card.id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def upsert_evolution_card(
        self, collection_id: int, run_id: str, content: str
    ) -> None:
        session = self._short_session()
        try:
            existing = (
                session.query(LibraryCard)
                .filter(
                    LibraryCard.collection_id == collection_id,
                    LibraryCard.card_type == "evolution",
                )
                .first()
            )
            if existing:
                existing.content = content
                existing.updated_at = datetime.now(UTC)
                existing.consolidation_run_id = run_id
            else:
                session.add(
                    LibraryCard(
                        collection_id=collection_id,
                        doc_id=str(uuid.uuid4()),
                        level="evolution",
                        title="Knowledge Evolution",
                        content=content,
                        card_type="evolution",
                        importance=0.8,
                        consolidation_run_id=run_id,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def fetch_previous_topic_labels(self, collection_id: int) -> set[str]:
        session = self._short_session()
        try:
            rows = (
                session.query(LibraryCard)
                .filter(
                    LibraryCard.collection_id == collection_id,
                    LibraryCard.card_type == "topic",
                )
                .all()
            )
            return {c.title for c in rows}
        finally:
            session.close()

    def has_previous_run(self, collection_guid: str, run_id: str) -> bool:
        session = self._short_session()
        try:
            previous = (
                session.query(ConsolidationRun)
                .filter(
                    ConsolidationRun.collection_id == collection_guid,
                    ConsolidationRun.id != run_id,
                )
                .order_by(ConsolidationRun.created_at.desc())
                .first()
            )
            return previous is not None
        finally:
            session.close()

    def add_gap_cards(self, collection_id: int, run_id: str, gaps: list[dict]) -> int:
        session = self._short_session()
        inserted = 0
        try:
            for gap in gaps:
                session.add(
                    LibraryCard(
                        collection_id=collection_id,
                        doc_id=str(uuid.uuid4()),
                        level="gap",
                        title=gap.get("topic", "Unknown Gap"),
                        content=gap.get("suggestion", ""),
                        card_type="gap",
                        importance=0.6,
                        consolidation_run_id=run_id,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
                inserted += 1
            session.commit()
            return inserted
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def fetch_search_misses(self, collection_guid: str, limit: int = 100) -> list[Any]:
        session = self._short_session()
        try:
            return (
                session.query(SearchMissLog)
                .filter(SearchMissLog.collection_id == collection_guid)
                .order_by(SearchMissLog.created_at.desc())
                .limit(limit)
                .all()
            )
        finally:
            session.close()

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
        session = self._short_session()
        try:
            session.add(
                ConsolidationRun(
                    id=run_id,
                    collection_id=collection_guid,
                    triggered_by="manual",
                    cards_created=cards_created,
                    cards_updated=cards_updated,
                    conflicts_found=conflicts_found,
                    gaps_found=gaps_found,
                    error=error,
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()
        except Exception as exc:
            logger.error("Failed to record consolidation run %s: %s", run_id, exc)
            try:
                session.rollback()
            except Exception:
                pass
        finally:
            session.close()
