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

import uuid
from typing import Any

from kapsula.core.domain.interfaces.chat_client import ChatClient
from kapsula.core.domain.interfaces.consolidation_card_repository import (
    ConsolidationCardRepository,
)
from kapsula.core.domain.json_utils import parse_json_safely
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

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

    Pure orchestration: every DB read/write is delegated to an injected
    :class:`ConsolidationCardRepository` (closes A2/S4). The runner holds
    no session and performs no ``session.add`` / ``session.query`` calls,
    so it is unit-testable with an in-memory repository fake.
    """

    def __init__(
        self,
        card_repository: ConsolidationCardRepository,
        chat_client: ChatClient,
        collection_id: int,
        collection_guid: str,
    ):
        self._cards = card_repository
        self._chat_client = chat_client
        self._collection_id = collection_id
        self._collection_guid = collection_guid
        self._run_id = str(uuid.uuid4())

        self._cards_created = 0
        self._cards_updated = 0
        self._conflicts_found = 0
        self._gaps_found = 0

    def run(self) -> dict[str, Any]:
        """Execute the full consolidation pipeline.

        A single ``record_run`` call covers every exit path (success, no
        work to do, or failure) so the audit row is written exactly once
        (closes M1 — previously four near-identical call sites). Control
        flow is preserved: when there are no extractive cards or no clusters
        form, gap-card generation is skipped just as before.
        """
        logger.info(
            "Starting consolidation for collection %s (run %s)",
            self._collection_guid,
            self._run_id,
        )

        error: str | None = None
        try:
            cards = self._cards.fetch_extractive_cards(self._collection_id)
            if cards:
                clusters = self._cluster_topics(cards)
                if clusters:
                    self._generate_topic_cards(clusters)
                    self._safe_call(
                        self._generate_evolution_card,
                        clusters,
                        label="Evolution card generation",
                    )
                    self._safe_call(
                        self._generate_gap_cards,
                        label="Gap card generation",
                    )
                else:
                    logger.info("No topic clusters formed")
            else:
                logger.info("No extractive cards to consolidate")

            logger.info(
                "Consolidation complete: %d created, %d updated, "
                "%d conflicts, %d gaps",
                self._cards_created,
                self._cards_updated,
                self._conflicts_found,
                self._gaps_found,
            )
        except Exception as exc:
            logger.exception("Consolidation failed: %s", exc)
            error = str(exc)

        self._cards.record_run(
            self._run_id,
            self._collection_guid,
            self._cards_created,
            self._cards_updated,
            self._conflicts_found,
            self._gaps_found,
            error=error,
        )
        return self._result()

    # ── step orchestration helpers ───────────────────────────

    def _generate_topic_cards(self, clusters: list[dict]) -> None:
        """Generate a topic card for each cluster, logging per-cluster failures."""
        for cluster in clusters:
            try:
                self._generate_topic_card(cluster)
            except Exception as exc:
                logger.error(
                    "Topic card generation failed for '%s': %s",
                    cluster.get("label", "?"),
                    exc,
                )

    def _safe_call(self, step, *args, label: str) -> None:
        """Run an optional LLM step, logging failures without aborting the run."""
        try:
            step(*args)
        except Exception as exc:
            logger.error("%s failed: %s", label, exc)

    # ── step implementations ─────────────────────────────────

    def _cluster_topics(self, cards: list) -> list[dict]:
        """Cluster cards into topics via LLM. No session held during the call."""
        existing_labels = self._cards.fetch_existing_topic_labels(self._collection_id)

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
            + "\n".join(card_entries[:100])
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

        plan = parse_json_safely(response)
        clusters = plan.get("topics", [])

        for cluster in clusters:
            indices = cluster.get("card_ids", [])
            cluster["_cards"] = [cards[i] for i in indices if 0 <= i < len(cards)]

        return clusters

    def _generate_topic_card(self, cluster: dict) -> None:
        """Generate a single topic card from a cluster of extractive cards.

        LLM call happens first; the DB write is delegated to the repository.
        """
        source_cards = cluster.get("_cards", [])
        if not source_cards:
            return

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

        result = parse_json_safely(response)
        contradictions = result.get("contradictions", [])
        self._conflicts_found += len(contradictions)

        # Clamp importance to [0.0, 1.0].
        raw_importance = result.get("importance", 0.5)
        try:
            importance = max(0.0, min(1.0, float(raw_importance)))
        except (TypeError, ValueError):
            importance = 0.5

        source_ids = [c.id for c in source_cards]
        status, _card_id = self._cards.upsert_topic_card(
            collection_id=self._collection_id,
            run_id=self._run_id,
            label=cluster.get("label", "Unknown"),
            summary=result.get("summary", ""),
            importance=importance,
            source_card_ids=source_ids,
            contradictions=contradictions or None,
        )
        if status == "created":
            self._cards_created += 1
        else:
            self._cards_updated += 1

    def _generate_evolution_card(self, clusters: list[dict]) -> None:
        """Generate an evolution card showing what changed since last run."""
        has_previous = self._cards.has_previous_run(self._collection_guid, self._run_id)

        if not has_previous:
            topic_labels = [c.get("label", "?") for c in clusters]
            content = (
                f"Initial consolidation: {len(clusters)} topics identified. "
                f"Topics: {', '.join(topic_labels[:10])}"
                + ("..." if len(topic_labels) > 10 else "")
            )
        else:
            prev_labels = self._cards.fetch_previous_topic_labels(self._collection_id)
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

        self._cards.upsert_evolution_card(
            collection_id=self._collection_id,
            run_id=self._run_id,
            content=content,
        )
        # The repository decides created vs updated; we count it as one update
        # for the summary (the exact created/updated split is tracked in topic cards).
        self._cards_updated += 1

    def _generate_gap_cards(self) -> None:
        """Analyze search miss log and generate gap cards."""
        misses = self._cards.fetch_search_misses(self._collection_guid, limit=100)
        if not misses:
            return

        query_text = "\n".join(
            f'- "{m.query}" ({m.result_count} results, score={m.top_score})'
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

        result = parse_json_safely(response)
        gaps = result.get("gaps", [])
        self._gaps_found = len(gaps)

        kept_gaps = [g for g in gaps if g.get("search_count", 0) >= 2]
        if not kept_gaps:
            return

        inserted = self._cards.add_gap_cards(
            collection_id=self._collection_id,
            run_id=self._run_id,
            gaps=kept_gaps,
        )
        self._cards_created += inserted

    def _result(self) -> dict[str, Any]:
        return {
            "run_id": self._run_id,
            "cards_created": self._cards_created,
            "cards_updated": self._cards_updated,
            "conflicts_found": self._conflicts_found,
            "gaps_found": self._gaps_found,
        }
