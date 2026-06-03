"""ConsolidationRunner — cross-document knowledge synthesis.

Phase 3 of the memory system. Runs as the final step of
collection maintenance, calling the LLM to:

1. Cluster extractive cards into topics
2. Generate Topic Cards (synthesized summaries)
3. Generate Evolution Cards (what changed since last run)
4. Generate Gap Cards (frequently searched, undocumented topics)
5. Write results as new LibraryCard + CardReference rows
"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

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
their source documents, group them into 3-8 coherent topics.

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
- If a card doesn't fit any group, put it in a "Miscellaneous" topic.
- Topic labels should be short (1-5 words), descriptive, and consistent.
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

importance: 0.0-1.0. Use 0.9+ for critical facts, 0.5 for background, 0.3 for trivia.
"""

_EVOLUTION_CARD_SYSTEM = """You track how a knowledge collection has changed over time.
Given the current set of topics and the previous consolidation state, produce a change summary.

Output ONLY valid JSON:
{
  "summary": "One sentence summary of what changed...",
  "changes": [
    {
      "type": "added|modified|removed",
      "topic": "Topic Name",
      "detail": "What changed specifically...",
      "sources": ["auth-arch.md"]
    }
  ]
}
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


# ── JSON parsing (shared with query_planner pattern) ────────


def _parse_json(text: str) -> dict:
    """Parse JSON from LLM output, handling code fences and prose."""
    if not text:
        raise ValueError("No text to parse")
    s = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s, re.IGNORECASE)
    if m:
        s = m.group(1).strip()
    else:
        s = s.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    if not (s.startswith("{") and s.endswith("}")):
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end != -1 and end > start:
            s = s[start : end + 1]
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    return json.loads(s)


# ── ConsolidationRunner ─────────────────────────────────────


class ConsolidationRunner:
    """Runs cross-document knowledge consolidation for a collection."""

    def __init__(
        self,
        db: Session,
        chat_client: ChatClient,
        collection_id: int,
        collection_guid: str,
    ):
        self._db = db
        self._chat_client = chat_client
        self._collection_id = collection_id
        self._collection_guid = collection_guid
        self._run_id = str(uuid.uuid4())

        self.cards_created = 0
        self.cards_updated = 0
        self.conflicts_found = 0
        self.gaps_found = 0

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

            # Step 1: cluster into topics
            clusters = self._cluster_topics(cards)
            if not clusters:
                logger.info("No topic clusters formed")
                self._record_run(error=None)
                return self._result()

            # Step 2: generate topic cards per cluster
            card_id_map = {c.id: c for c in cards}
            for cluster in clusters:
                try:
                    self._generate_topic_card(cluster, card_id_map)
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
                self.cards_created,
                self.cards_updated,
                self.conflicts_found,
                self.gaps_found,
            )
            return self._result()

        except Exception as exc:
            logger.error("Consolidation failed: %s", exc, exc_info=True)
            self._record_run(error=str(exc))
            return self._result()

    # ── step implementations ─────────────────────────────────

    def _gather_extractive_cards(self) -> list[LibraryCard]:
        """Return all H2/H3 extractive cards for the collection."""
        return (
            self._db.query(LibraryCard)
            .filter(
                LibraryCard.collection_id == self._collection_id,
                LibraryCard.level.in_(["level_2", "level_3"]),
            )
            .order_by(LibraryCard.title)
            .all()
        )

    def _cluster_topics(self, cards: list[LibraryCard]) -> list[dict]:
        """Cluster cards into topics via LLM."""
        # Build flat card list for the LLM
        card_entries = []
        for i, card in enumerate(cards):
            preview = card.content[:200].replace("\n", " ").strip()
            doc_name = card.document.filename if card.document else "?"
            card_entries.append(
                f"[id={i}] [{card.level}] {card.title} "
                f"(doc: {doc_name}) — {preview}"
            )

        user_message = (
            "Group these knowledge sections into topics:\n\n"
            + "\n".join(card_entries[:100])  # limit to 100 cards
        )

        response = self._chat_client.send(
            messages=[
                {"role": "system", "content": _TOPIC_CLUSTERING_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            max_tokens=1000,
            temperature=0.3,
        )

        plan = _parse_json(response)
        clusters = plan.get("topics", [])

        # Map LLM indices back to card objects
        for cluster in clusters:
            indices = cluster.get("card_ids", [])
            cluster["_cards"] = [cards[i] for i in indices if 0 <= i < len(cards)]

        return clusters

    def _generate_topic_card(
        self, cluster: dict, card_id_map: dict[int, LibraryCard]
    ) -> None:
        """Generate a single topic card from a cluster of extractive cards."""
        source_cards = cluster.get("_cards", [])
        if not source_cards:
            return

        # Build context for the LLM
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

        response = self._chat_client.send(
            messages=[
                {"role": "system", "content": _TOPIC_CARD_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            max_tokens=800,
            temperature=0.3,
        )

        result = _parse_json(response)
        contradictions = result.get("contradictions", [])
        self.conflicts_found += len(contradictions)

        # Upsert: find existing topic card for this label
        existing = (
            self._db.query(LibraryCard)
            .filter(
                LibraryCard.collection_id == self._collection_id,
                LibraryCard.card_type == "topic",
                LibraryCard.title == cluster.get("label", ""),
            )
            .first()
        )

        if existing:
            existing.content = result.get("summary", "")
            existing.importance = result.get("importance", 0.5)
            existing.updated_at = datetime.now(UTC)
            existing.consolidation_run_id = self._run_id
            card = existing
            self.cards_updated += 1
        else:
            card = LibraryCard(
                collection_id=self._collection_id,
                doc_id=str(uuid.uuid4()),
                level="topic",
                title=cluster.get("label", "Unknown"),
                content=result.get("summary", ""),
                card_type="topic",
                importance=result.get("importance", 0.5),
                consolidation_run_id=self._run_id,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            self._db.add(card)
            self._db.flush()  # get card.id
            self.cards_created += 1

        # Link to source cards
        for source in source_cards:
            ref = CardReference(
                source_card_id=card.id,
                target_card_id=source.id,
                relation_type="synthesizes_from",
            )
            self._db.add(ref)

        # Record contradictions as card references
        for contradiction in contradictions:
            # Store contradiction info in a gap/conflict reference
            ref = CardReference(
                source_card_id=card.id,
                target_card_id=card.id,  # self-reference for metadata
                relation_type="contradicts",
            )
            self._db.add(ref)

    def _generate_evolution_card(self, clusters: list[dict]) -> None:
        """Generate an evolution card showing what changed since last run."""
        # Get previous consolidation run
        previous = (
            self._db.query(ConsolidationRun)
            .filter(
                ConsolidationRun.collection_id == self._collection_guid,
                ConsolidationRun.id != self._run_id,
            )
            .order_by(ConsolidationRun.created_at.desc())
            .first()
        )

        if not previous:
            # First run — create a baseline evolution card
            topic_labels = [c.get("label", "?") for c in clusters]
            content = (
                f"Initial consolidation: {len(clusters)} topics identified. "
                f"Topics: {', '.join(topic_labels[:10])}"
                + ("..." if len(topic_labels) > 10 else "")
            )
        else:
            # Compare current topics to previous
            current_labels = {c.get("label", "") for c in clusters}
            prev_cards = (
                self._db.query(LibraryCard)
                .filter(
                    LibraryCard.collection_id == self._collection_id,
                    LibraryCard.card_type == "topic",
                )
                .all()
            )
            prev_labels = {c.title for c in prev_cards}

            added = current_labels - prev_labels
            removed = prev_labels - current_labels
            kept = current_labels & prev_labels

            changes = []
            if added:
                changes.append(f"Added: {', '.join(sorted(added))}")
            if removed:
                changes.append(f"Removed: {', '.join(sorted(removed))}")
            if not changes:
                changes.append(
                    f"No topic changes. {len(kept)} topics re-evaluated."
                )

            content = f"Consolidation update. " + "; ".join(changes)

        # Upsert evolution card
        existing = (
            self._db.query(LibraryCard)
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
            self.cards_updated += 1
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
            self._db.add(card)
            self.cards_created += 1

    def _generate_gap_cards(self) -> None:
        """Analyze search miss log and generate gap cards."""
        misses = (
            self._db.query(SearchMissLog)
            .filter(SearchMissLog.collection_id == self._collection_guid)
            .order_by(SearchMissLog.created_at.desc())
            .limit(100)
            .all()
        )

        if not misses:
            return

        # Build query list for the LLM
        query_text = "\n".join(
            f"- \"{m.query}\" ({m.result_count} results, score={m.top_score})"
            for m in misses[:50]
        )

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

        result = _parse_json(response)
        gaps = result.get("gaps", [])
        self.gaps_found = len(gaps)

        for gap in gaps:
            if gap.get("search_count", 0) < 2:
                continue

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
            self._db.add(card)
            self.cards_created += 1

    def _record_run(self, error: str | None) -> None:
        """Persist the consolidation_run row."""
        run = ConsolidationRun(
            id=self._run_id,
            collection_id=self._collection_guid,
            triggered_by="manual",
            cards_created=self.cards_created,
            cards_updated=self.cards_updated,
            conflicts_found=self.conflicts_found,
            gaps_found=self.gaps_found,
            error=error,
            created_at=datetime.now(UTC),
        )
        self._db.add(run)
        self._db.commit()

    def _result(self) -> dict[str, Any]:
        return {
            "run_id": self._run_id,
            "cards_created": self.cards_created,
            "cards_updated": self.cards_updated,
            "conflicts_found": self.conflicts_found,
            "gaps_found": self.gaps_found,
        }
