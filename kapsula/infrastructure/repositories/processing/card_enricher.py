"""CardEnricher — generates one-line descriptions for terse structural titles.

Slice 2 of the consolidation-quality spec. Structural library cards (H1/H2/H3)
inherit titles verbatim from document headings, which are often terse or
context-dependent ("Architecture", "Clare Sullivan"). This enricher calls the
LLM to produce a one-line description from the card content, so an agent
browsing ``get_library_cards`` can decide whether to query without opening
the document.

Design: each card is enriched in its own short transaction (mirrors the
consolidation runner's short-lived-transaction pattern). The LLM call happens
outside any session.
"""

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from kapsula.core.domain.interfaces.chat_client import ChatClient
from kapsula.infrastructure.data import LibraryCard

logger = logging.getLogger(__name__)

_ENRICH_SYSTEM = """You write one-line library card descriptions.

Given a section's heading and its first paragraph of content, produce a single
concise sentence (max ~20 words) describing what the section is about. The
description should let a reader decide whether to read the section WITHOUT
opening it. Focus on the specific subject, not the heading's literal words.

Output ONLY the description sentence — no preamble, no quotes, no markdown."""


class CardEnricher:
    """Enriches structural library cards with one-line descriptions."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        chat_client: ChatClient,
        collection_id: int,
        collection_guid: str,
    ):
        self._session_factory = session_factory
        self._chat_client = chat_client
        self._collection_id = collection_id
        self._collection_guid = collection_guid

    def run(self, batch_limit: int = 100) -> dict:
        """Enrich structural cards missing descriptions.

        Args:
            batch_limit: Max cards to enrich in one run (each is an LLM call).

        Returns:
            Dict with enriched/skipped/failed counts.
        """
        card_ids = self._fetch_cards_needing_enrichment(batch_limit)
        if not card_ids:
            logger.info(
                "No cards need enrichment in collection %s", self._collection_guid
            )
            return {"enriched": 0, "skipped": 0, "failed": 0}

        logger.info(
            "Enriching %d structural cards in collection %s",
            len(card_ids),
            self._collection_guid,
        )

        enriched = 0
        failed = 0
        for card_id, title, content in card_ids:
            try:
                description = self._generate_description(title, content)
                if description:
                    self._save_description(card_id, description)
                    enriched += 1
            except Exception as exc:
                logger.warning(
                    "Failed to enrich card %s ('%s'): %s", card_id, title, exc
                )
                failed += 1

        return {"enriched": enriched, "skipped": 0, "failed": failed}

    # ── helpers ──────────────────────────────────────────────

    def _short_session(self) -> Session:
        return self._session_factory()

    def _fetch_cards_needing_enrichment(self, limit: int):
        """Return (id, title, content) for structural cards missing descriptions."""
        session = self._short_session()
        try:
            rows = (
                session.query(LibraryCard.id, LibraryCard.title, LibraryCard.content)
                .filter(
                    LibraryCard.collection_id == self._collection_id,
                    LibraryCard.card_type == "extractive",
                    LibraryCard.level.in_(["level_1", "level_2", "level_3"]),
                    LibraryCard.description.is_(None),
                )
                .order_by(LibraryCard.id)
                .limit(limit)
                .all()
            )
            return rows
        finally:
            session.close()

    def _generate_description(self, title: str, content: str) -> str | None:
        """Call the LLM to produce a one-line description. No session held."""
        if not content:
            return None
        # Use the first ~500 chars of content for context
        preview = content[:500].replace("\n", " ").strip()
        if not preview:
            return None

        user_message = (
            f"Heading: {title}\n\n"
            f"Section content:\n{preview}\n\n"
            f"Write a one-line description of what this section is about."
        )

        response = self._chat_client.send(
            messages=[
                {"role": "system", "content": _ENRICH_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            max_tokens=80,
            temperature=0.2,
        )

        description = (response or "").strip().strip('"').strip("'").strip()
        # Sanity: discard if empty or suspiciously long
        if not description or len(description) > 200:
            return None
        return description

    def _save_description(self, card_id: int, description: str) -> None:
        """Persist the description in a short transaction."""
        session = self._short_session()
        try:
            card = session.query(LibraryCard).filter(LibraryCard.id == card_id).first()
            if card:
                card.description = description
                session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
