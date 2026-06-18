"""ConsolidationRunner — cross-document knowledge synthesis.

Phase 3 of the memory system. Runs as the final step of
collection maintenance, calling the LLM to:

1. Cluster extractive cards into topics
2. Generate Topic Cards (synthesized summaries)
3. Generate Evolution Cards (what changed since last run)
4. Generate Gap Cards (frequently searched, undocumented topics)
5. Write results as new LibraryCard + CardReference rows

Transaction design: each DB write happens in a short-lived session that is
opened after the LLM call returns and closed immediately after commit. This
keeps SQLite write locks held only for the brief write (ms), never across
long LLM network calls. See spec 2026-06-17_short-lived-write-transactions.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy.orm import Session, joinedload

from kapsula.core.domain.json_utils import _parse_json_safely
from kapsula.core.domain.interfaces.chat_client import ChatClient
from kapsula.infrastructure.data import (
    CardReference,
    ConsolidationRun,
    LibraryCard,
    SearchMissLog,
)

logger = logging.getLogger(__name__)

# ── LLM prompts ─────────────────────────────────────────────

_TOPIC_CLUSTERING_SYSTEM = """You are a knowledge organizer. Given a list of section headings and
their source documents, group them into 3-8 coherent, SPECIFIC topics.

Output ONLY valid JSON with this structure:
{
  "topics": [
    {
      "label": "Topic Name",
      "card_ids": [1, 2, 3],
      "rationale": "These cards all discuss..."
    }
  ]
}

Rules:
- Each card_id must appear in exactly one topic group.
- Group cards that discuss the same subject, even if from different documents.
- Create SPECIFIC, descriptive topic labels (2-6 words). E.g., "BIS Clearinghouse
  Architecture", not just "Banking".
- AVOID creating a "Miscellaneous" or "Other" group. Find the best-fitting specific
  topic for every card, even if the fit is imperfect. Only as a last resort, a
  single "Unclassified" group is permitted.
- If existing topic labels are provided below, REUSE those exact labels when a
  cluster matches an existing topic. Only create a NEW label for genuinely new
  topics. This prevents duplicate near-identical topic cards across runs.
"""

_TOPIC_CARD_SYSTEM = """You are a knowledge synthesizer. Given multiple text sections about the
same topic, produce a concise, factual summary that captures the key information.

Output ONLY valid JSON:
{
  "summary": "One paragraph synthesizing the key facts from all sources...",
  "key_facts": ["Fact 1", "Fact 2"],
  "importance": 0.8,
  "contradictions": []
}

If you detect conflicting information across sources, list each contradiction:
{
  "contradictions": [
    {
      "claim_a": "Token expiry is 30 minutes (from auth-arch.md)",
      "claim_b": "Token expiry is 15 minutes (from api-security.md)",
      "resolution_note": "api-security.md is newer (uploaded June 1)"
    }
  ]
}

importance: rate how central this topic is to the collection's argument.
  1.0 = Foundational (the argument collapses without it; many other topics reference it)
  0.8 = Core mechanism (named institutions, specific processes, dates, key actors)
  0.6 = Supporting evidence (case studies, examples, historical parallels)
  0.4 = Contextual background (definitions, framing, peripheral mentions)
ALWAYS return a value in [0.0, 1.0]. NEVER return negative values or values above 1.0.
Analytical frameworks and critiques of the central thesis are HIGH importance
(foundational), not low — they are the argument's core, not trivia.
"""


_GAP_CARD_SYSTEM = """You analyze search patterns to identify knowledge gaps.
Given a list of searches that returned few or no results, identify patterns
and suggest what knowledge is missing.

Output ONLY valid JSON:
{
  "gaps": [
    {
      "topic": "Missing Topic Name",
      "search_count": 4,
      "suggestion": "Consider documenting..."
    }
  ]
}

- Only include gaps with 2+ searches.
- Group similar queries under one topic.
- suggestion should be actionable (what document to create).
"""


# ── ConsolidationRunner ─────────────────────────────────────


class ConsolidationRunner:
    """Runs cross-document knowledge consolidation for a collection.

    Uses a session factory so each write step opens a short transaction
    after the LLM call returns, keeping SQLite write locks brief.
    """

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
        self._run_id = str(uuid.uuid4())

        self._cards_created = 0
        self._cards_updated = 0
        self._conflicts_found = 0
        self._gaps_found = 0

    def run(self) -> dict[str, Any]:
        """Execute the full consolidation pipeline."""
        logger.info(
            "Starting consolidation for collection %s (run %s)",
            self._collection_guid,
            self._run_id,
        )

        try:
            cards = self._gather_extractive_cards()
            if not cards:
                logger.info("No extractive cards to consolidate")
                self._record_run(error=None)
                return self._result()

            # Step 1: cluster into topics (LLM call — no session held)
            clusters = self._cluster_topics(cards)
            if not clusters:
                logger.info("No topic clusters formed")
                self._record_run(error=None)
                return self._result()

            # Step 2: generate topic cards per cluster (each writes in its
            # own short transaction, so a per-card failure is isolated).
            for cluster in clusters:
                try:
                    self._generate_topic_card(cluster)
                except Exception as exc:
                    logger.error(
                        "Topic card generation failed for '%s': %s",
                        cluster.get("label", "?"),
                        exc,
                    )

            # Step 3: generate evolution card
            try:
                self._generate_evolution_card(clusters)
            except Exception as exc:
                logger.error("Evolution card generation failed: %s", exc)

            # Step 4: generate gap cards from search miss log
            try:
                self._generate_gap_cards()
            except Exception as exc:
                logger.error("Gap card generation failed: %s", exc)

            self._record_run(error=None)
            logger.info(
                "Consolidation complete: %d created, %d updated, "
                "%d conflicts, %d gaps",
                self._cards_created,
                self._cards_updated,
                self._conflicts_found,
                self._gaps_found,
            )
            return self._result()

        except Exception as exc:
            logger.error("Consolidation failed: %s", exc, exc_info=True)
            self._record_run(error=str(exc))
            return self._result()

    # ── helpers ──────────────────────────────────────────────

    def _short_session(self) -> Session:
        """Open a fresh session for a short transaction. Caller MUST close."""
        return self._session_factory()

    # ── step implementations ─────────────────────────────────

    def _gather_extractive_cards(self) -> list[LibraryCard]:
        """Return all H2/H3 extractive cards for the collection (detached)."""
        session = self._short_session()
        try:
            cards = (
                session.query(LibraryCard)
                .options(joinedload(LibraryCard.document))
                .filter(
                    LibraryCard.collection_id == self._collection_id,
                    LibraryCard.card_type == "extractive",
                    LibraryCard.level.in_(["level_2", "level_3"]),
                )
                .order_by(LibraryCard.title)
                .all()
            )
            for card in cards:
                session.expunge(card)  # detach so it survives session close
            return cards
        finally:
            session.close()

    def _fetch_existing_topic_labels(self) -> list[str]:
        """Return existing topic card labels for this collection (for dedup)."""
        session = self._short_session()
        try:
            rows = (
                session.query(LibraryCard.title)
                .filter(
                    LibraryCard.collection_id == self._collection_id,
                    LibraryCard.card_type == "topic",
                )
                .all()
            )
            return [r[0] for r in rows if r[0]]
        finally:
            session.close()

    def _cluster_topics(self, cards: list[LibraryCard]) -> list[dict]:
        """Cluster cards into topics via LLM. No session held during the call.

        Existing topic labels are passed to the prompt so the LLM reuses them
        rather than inventing near-duplicate labels across runs.
        """
        existing_labels = self._fetch_existing_topic_labels()

        # Build flat card list for the LLM
        card_entries = []
        for i, card in enumerate(cards):
            preview = card.content[:200].replace("\n", " ").strip()
            doc_name = card.document.filename if card.document else "?"
            card_entries.append(
                f"[id={i}] [{card.level}] {card.title} "
                f"(doc: {doc_name}) — {preview}"
            )

        label_hint = ""
        if existing_labels:
            label_hint = (
                "\n\nExisting topics in this collection (REUSE these exact labels "
                "if a cluster matches; only create a NEW label for genuinely new topics):\n"
                + "\n".join(f"- {label}" for label in existing_labels)
            )

        user_message = (
            "Group these knowledge sections into topics:\n\n"
            + "\n".join(card_entries[:100])  # limit to 100 cards
            + label_hint
        )

        response = self._chat_client.send(
            messages=[
                {"role": "system", "content": _TOPIC_CLUSTERING_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            max_tokens=4000,
            temperature=0.3,
        )

        plan = _parse_json_safely(response)
        clusters = plan.get("topics", [])

        # Map LLM indices back to card objects
        for cluster in clusters:
            indices = cluster.get("card_ids", [])
            cluster["_cards"] = [cards[i] for i in indices if 0 <= i < len(cards)]

        return clusters

    def _generate_topic_card(self, cluster: dict) -> None:
        """Generate a single topic card from a cluster of extractive cards.

        LLM call happens first (no session); the DB write runs in a short
        transaction that commits before returning.
        """
        source_cards = cluster.get("_cards", [])
        if not source_cards:
            return

        # Build context for the LLM (uses detached card objects)
        sections = []
        for card in source_cards:
            doc_name = card.document.filename if card.document else "?"
            sections.append(
                f"--- Source: {doc_name}, Section: {card.title} ---\n{card.content[:2000]}"
            )

        user_message = (
            f"Topic: {cluster.get('label', 'Unknown')}\n\n"
            + "Synthesize these sections into a coherent summary:\n\n"
            + "\n\n".join(sections[:10])
        )

        # LLM call — NO session open
        response = self._chat_client.send(
            messages=[
                {"role": "system", "content": _TOPIC_CARD_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            max_tokens=800,
            temperature=0.3,
        )

        result = _parse_json_safely(response)
        contradictions = result.get("contradictions", [])
        self._conflicts_found += len(contradictions)

        # Clamp importance to [0.0, 1.0] — defense in depth against LLM returning
        # negative escape-hatch values or values > 1.
        raw_importance = result.get("importance", 0.5)
        try:
            importance = max(0.0, min(1.0, float(raw_importance)))
        except (TypeError, ValueError):
            importance = 0.5

        # DB write — short transaction
        session = self._short_session()
        try:
            existing = (
                session.query(LibraryCard)
                .filter(
                    LibraryCard.collection_id == self._collection_id,
                    LibraryCard.card_type == "topic",
                    LibraryCard.title == cluster.get("label", ""),
                )
                .first()
            )

            if existing:
                existing.content = result.get("summary", "")
                existing.importance = importance
                existing.updated_at = datetime.now(UTC)
                existing.consolidation_run_id = self._run_id
                card = existing
                self._cards_updated += 1
            else:
                card = LibraryCard(
                    collection_id=self._collection_id,
                    doc_id=str(uuid.uuid4()),
                    level="topic",
                    title=cluster.get("label", "Unknown"),
                    content=result.get("summary", ""),
                    card_type="topic",
                    importance=importance,
                    consolidation_run_id=self._run_id,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                session.add(card)
                session.flush()  # get card.id
                self._cards_created += 1

            # Link to source cards
            for source in source_cards:
                ref = CardReference(
                    source_card_id=card.id,
                    target_card_id=source.id,
                    relation_type="synthesizes_from",
                )
                session.add(ref)

            # Store contradiction details
            if contradictions:
                card.extra_metadata = json.dumps({"contradictions": contradictions})

            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _generate_evolution_card(self, clusters: list[dict]) -> None:
        """Generate an evolution card showing what changed since last run.

        Reads + LLM call + write are split so the write lock is held briefly.
        """
        # Read previous run + existing topics in a short session
        session = self._short_session()
        try:
            previous = (
                session.query(ConsolidationRun)
                .filter(
                    ConsolidationRun.collection_id == self._collection_guid,
                    ConsolidationRun.id != self._run_id,
                )
                .order_by(ConsolidationRun.created_at.desc())
                .first()
            )

            prev_labels: set[str] = set()
            if previous:
                prev_cards = (
                    session.query(LibraryCard)
                    .filter(
                        LibraryCard.collection_id == self._collection_id,
                        LibraryCard.card_type == "topic",
                    )
                    .all()
                )
                prev_labels = {c.title for c in prev_cards}
        finally:
            session.close()

        # Compute content (no session needed)
        if not previous:
            topic_labels = [c.get("label", "?") for c in clusters]
            content = (
                f"Initial consolidation: {len(clusters)} topics identified. "
                f"Topics: {', '.join(topic_labels[:10])}"
                + ("..." if len(topic_labels) > 10 else "")
            )
        else:
            current_labels = {c.get("label", "") for c in clusters}
            added = current_labels - prev_labels
            removed = prev_labels - current_labels
            kept = current_labels & prev_labels

            changes = []
            if added:
                changes.append(f"Added: {', '.join(sorted(added))}")
            if removed:
                changes.append(f"Removed: {', '.join(sorted(removed))}")
            if not changes:
                changes.append(f"No topic changes. {len(kept)} topics re-evaluated.")

            content = "Consolidation update. " + "; ".join(changes)

        # Write in a short session
        session = self._short_session()
        try:
            existing = (
                session.query(LibraryCard)
                .filter(
                    LibraryCard.collection_id == self._collection_id,
                    LibraryCard.card_type == "evolution",
                )
                .first()
            )

            if existing:
                existing.content = content
                existing.updated_at = datetime.now(UTC)
                existing.consolidation_run_id = self._run_id
                self._cards_updated += 1
            else:
                card = LibraryCard(
                    collection_id=self._collection_id,
                    doc_id=str(uuid.uuid4()),
                    level="evolution",
                    title="Knowledge Evolution",
                    content=content,
                    card_type="evolution",
                    importance=0.8,
                    consolidation_run_id=self._run_id,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                session.add(card)
                self._cards_created += 1

            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _generate_gap_cards(self) -> None:
        """Analyze search miss log and generate gap cards.

        Read misses + LLM call + writes are split into short transactions.
        """
        # Read misses in a short session
        session = self._short_session()
        try:
            misses = (
                session.query(SearchMissLog)
                .filter(SearchMissLog.collection_id == self._collection_guid)
                .order_by(SearchMissLog.created_at.desc())
                .limit(100)
                .all()
            )
            miss_data = [(m.query, m.result_count, m.top_score) for m in misses]
        finally:
            session.close()

        if not miss_data:
            return

        # Build query list for the LLM
        query_text = "\n".join(
            f'- "{q}" ({count} results, score={score})'
            for q, count, score in miss_data[:50]
        )

        # LLM call — NO session open
        response = self._chat_client.send(
            messages=[
                {"role": "system", "content": _GAP_CARD_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        "These searches returned few or no results. "
                        "Identify knowledge gaps:\n\n" + query_text
                    ),
                },
            ],
            max_tokens=500,
            temperature=0.3,
        )

        result = _parse_json_safely(response)
        gaps = result.get("gaps", [])
        self._gaps_found = len(gaps)

        kept_gaps = [g for g in gaps if g.get("search_count", 0) >= 2]
        if not kept_gaps:
            return

        # Write gap cards in a short session
        session = self._short_session()
        try:
            for gap in kept_gaps:
                card = LibraryCard(
                    collection_id=self._collection_id,
                    doc_id=str(uuid.uuid4()),
                    level="gap",
                    title=gap.get("topic", "Unknown Gap"),
                    content=gap.get("suggestion", ""),
                    card_type="gap",
                    importance=0.6,
                    consolidation_run_id=self._run_id,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                session.add(card)
                self._cards_created += 1

            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _record_run(self, error: str | None) -> None:
        """Persist the consolidation_run row in its own short transaction."""
        session = self._short_session()
        try:
            run = ConsolidationRun(
                id=self._run_id,
                collection_id=self._collection_guid,
                triggered_by="manual",
                cards_created=self._cards_created,
                cards_updated=self._cards_updated,
                conflicts_found=self._conflicts_found,
                gaps_found=self._gaps_found,
                error=error,
                created_at=datetime.now(UTC),
            )
            session.add(run)
            session.commit()
        except Exception as exc:
            logger.error(
                "Failed to record consolidation run %s: %s", self._run_id, exc
            )
            try:
                session.rollback()
            except Exception:
                pass
        finally:
            session.close()

    def _result(self) -> dict[str, Any]:
        return {
            "run_id": self._run_id,
            "cards_created": self._cards_created,
            "cards_updated": self._cards_updated,
            "conflicts_found": self._conflicts_found,
            "gaps_found": self._gaps_found,
        }
