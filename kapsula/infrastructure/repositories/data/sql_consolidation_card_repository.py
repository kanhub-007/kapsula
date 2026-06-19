"""SQLAlchemy-backed ConsolidationCardRepository.

Owns every DB read/write that ConsolidationRunner previously performed
inline. Each method opens a short transaction so SQLite write locks are
held only for the brief write, never across long LLM calls (per the
``short-lived-write-transactions`` spec).
"""

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import joinedload

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

    def _short_session(self):
        """Open a fresh session. Caller MUST close."""
        return self._session_factory()

    @contextmanager
    def _session(self):
        """Short-lived session with automatic rollback/close (closes M2).

        Replaces the ``session = self._short_session(); try: ... except:
        rollback; raise; finally: close`` boilerplate that was copy-pasted
        across every write method. Reads also use this so cursor cleanup is
        uniform. Commit is the caller's responsibility; on any exception we
        roll back and re-raise.
        """
        session = self._short_session()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def fetch_extractive_cards(self, collection_id: int) -> list[Any]:
        with self._session() as session:
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

    def fetch_existing_topic_labels(self, collection_id: int) -> list[str]:
        with self._session() as session:
            rows = (
                session.query(LibraryCard.title)
                .filter(
                    LibraryCard.collection_id == collection_id,
                    LibraryCard.card_type == "topic",
                )
                .all()
            )
            return [r[0] for r in rows if r[0]]

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

        with self._session() as session:
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

    def upsert_evolution_card(
        self, collection_id: int, run_id: str, content: str
    ) -> None:
        with self._session() as session:
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

    def fetch_previous_topic_labels(self, collection_id: int) -> set[str]:
        with self._session() as session:
            rows = (
                session.query(LibraryCard)
                .filter(
                    LibraryCard.collection_id == collection_id,
                    LibraryCard.card_type == "topic",
                )
                .all()
            )
            return {c.title for c in rows}

    def has_previous_run(self, collection_guid: str, run_id: str) -> bool:
        with self._session() as session:
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

    def add_gap_cards(self, collection_id: int, run_id: str, gaps: list[dict]) -> int:
        inserted = 0
        with self._session() as session:
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

    def fetch_search_misses(self, collection_guid: str, limit: int = 100) -> list[Any]:
        with self._session() as session:
            return (
                session.query(SearchMissLog)
                .filter(SearchMissLog.collection_id == collection_guid)
                .order_by(SearchMissLog.created_at.desc())
                .limit(limit)
                .all()
            )

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
        """Persist the ConsolidationRun audit row.

        Unlike the other write methods, this does NOT swallow persistence
        failures: the ConsolidationRun table is an audit log, and silently
        dropping a row here would hide the fact that a run happened at all
        (closes M11). The caller (ConsolidationRunner) already guards the
        whole run with a top-level try/except.
        """
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
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
