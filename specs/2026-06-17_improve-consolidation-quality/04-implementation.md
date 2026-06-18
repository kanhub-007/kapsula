# Implementation Guide — Improve Consolidation Quality

---

### Step 1: Prompt-based dedup (pass existing labels to clustering)
**File:** `kapsula/infrastructure/repositories/processing/consolidation_runner.py`, `_cluster_topics`

**Problem:** Each run invents labels independently; similar clusters create near-duplicate cards. String-matching dedup was tested and fails (SequenceMatcher catches 1/6 duplicates; the duplicates are semantically similar but lexically different).

**Fix:** Fetch existing topic labels before clustering and include them in the prompt so the LLM reuses them. This leverages the LLM's semantic understanding rather than brittle string metrics.

```python
def _cluster_topics(self, cards: list[LibraryCard]) -> list[dict]:
    # Fetch existing topic labels for this collection
    existing_labels = self._fetch_existing_topic_labels()

    # Build the user message including existing labels
    label_hint = ""
    if existing_labels:
        label_hint = (
            "\n\nExisting topics in this collection (REUSE these exact labels "
            "if a cluster matches; only create a NEW label for genuinely new topics):\n"
            + "\n".join(f"- {label}" for label in existing_labels)
        )

    user_message = "Group these knowledge sections into topics:\n\n" + "\n".join(
        card_entries[:100]
    ) + label_hint
    ...
```

`_fetch_existing_topic_labels` opens a short session, queries topic titles, closes:
```python
def _fetch_existing_topic_labels(self) -> list[str]:
    session = self._short_session()
    try:
        rows = session.query(LibraryCard.title).filter(
            LibraryCard.collection_id == self._collection_id,
            LibraryCard.card_type == "topic",
        ).all()
        return [r[0] for r in rows]
    finally:
        session.close()
```

**Why this is better than fuzzy matching:** The LLM sees "Financial & Digital Control Infrastructure" exists and reuses it, rather than independently inventing "Financial Surveillance & Control Infrastructure." No threshold to tune, no false negatives on semantically-similar-but-lexically-different labels.

**Verify:** Run consolidation twice — second run should not create near-duplicate labels.

---

### Step 2: Rewrite the importance prompt and clamp values
**File:** `consolidation_runner.py`, `_TOPIC_CARD_SYSTEM` prompt and `_generate_topic_card`

**Problem:** The current prompt (`importance: 0.0-1.0. Use 0.9+ for critical facts, 0.5 for background, 0.3 for trivia.`) is vague, produced bimodal clustering (88% at 0.7+), and the LLM used negative values as an escape hatch for analytical content — hiding the most substantive cards from search context.

**Fix — Part A: Rewrite the prompt to ground the scale:**

```python
_TOPIC_CARD_SYSTEM = """You are a knowledge synthesizer. Given multiple text sections about the
same topic, produce a concise, factual summary that captures the key information.

Output ONLY valid JSON:
{
  "summary": "One paragraph synthesizing the key facts from all sources...",
  "key_facts": ["Fact 1", "Fact 2"],
  "importance": 0.8,
  "contradictions": []
}

importance: rate how central this topic is to the collection's argument.
  1.0 = Foundational (the argument collapses without it; many other topics reference it)
  0.8 = Core mechanism (named institutions, specific processes, dates, key actors)
  0.6 = Supporting evidence (case studies, examples, historical parallels)
  0.4 = Contextual background (definitions, framing, peripheral mentions)
ALWAYS return a value in [0.0, 1.0]. NEVER return negative values or values above 1.0.
Analytical frameworks and critiques of the central thesis are HIGH importance (foundational),
not low — they are the argument's core, not trivia.

If you detect conflicting information across sources, list each contradiction:
{ "contradictions": [ ... ] }
"""
```

Key changes:
- "centrality to the argument" replaces vague "critical facts / background / trivia"
- Concrete anchors per band (foundational / mechanism / evidence / background)
- Explicit "NEVER negative" + "analytical frameworks are HIGH"
- Addresses the inverted case where "The Meta-Constitution" got -1.0

**Fix — Part B: Clamp regardless (defense in depth):**

```python
raw_importance = result.get("importance", 0.5)
try:
    importance = max(0.0, min(1.0, float(raw_importance)))
except (TypeError, ValueError):
    importance = 0.5
```

Apply in both insert and update branches of `_generate_topic_card`.

**Verify:**
- Query all topic cards — all importance in [0, 1]
- "The Meta-Constitution" / "Critiques of Marxism" re-score to >= 0.7 after re-consolidation
- Distribution spreads more evenly (not 88% bunched at 0.7+)

---

### Step 3: Tighten the clustering prompt
**File:** `consolidation_runner.py`, `_TOPIC_CLUSTERING_SYSTEM`

**Problem:** "Miscellaneous" is too easy an escape hatch (7/7 collections have one).

**Fix:** Replace the Miscellaneous invitation with a preference for specific topics:

```
Rules:
- Each card_id must appear in exactly one topic group.
- Group cards that discuss the same subject, even if from different documents.
- Create SPECIFIC, descriptive topic labels (2-6 words). E.g., "BIS Clearinghouse Architecture",
  not just "Banking".
- AVOID creating a "Miscellaneous" or "Other" group. Find the best-fitting specific topic
  for every card, even if the fit is imperfect. Only as a last resort, a single
  "Unclassified" group is permitted.
```

**Verify:** After re-consolidation, at most 1 Miscellaneous/Unclassified per collection.

---

### Step 4: Strip image markdown from structural card content
**File:** `kapsula/presentation/api/tasks.py:915` (where `parent_card = LibraryCard(content=section_data["content"])`)

**Problem:** 53% of structural cards have image markdown in their content, dominating previews. (Note: the search index is clean — chunking already strips images. This fix is card-content-only.)

**Fix:** Strip leading image markdown from the section content before storing it in the card:

```python
import re

def _strip_leading_images(content: str) -> str:
    """Remove leading image/figure markdown so card previews show real text."""
    # Remove ![alt](url) patterns
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", content)
    # Remove leading "Figure N:" / "fig N" labels
    cleaned = re.sub(r"^\s*fig(?:ure)?\s*\d*[:.]?\s*", "", cleaned, flags=re.IGNORECASE)
    # Collapse leading whitespace/newlines left by removed images
    return cleaned.lstrip()
```

Apply at card creation:
```python
parent_card = LibraryCard(
    ...
    content=_strip_leading_images(section_data["content"]),
    ...
)
```

**Scope note:** This strips ALL image markdown from card content (not just the first 200 chars), which is correct — the full card content is browsable, not just the preview. It does NOT touch chunk content (already clean) or the search index.

**Trade-off:** Stripping all images removes the occasional legitimate diagram reference. Acceptable — diagrams are referenced by URL (broken in text anyway) and the surrounding prose describes them.

**Verify:** Browse `get_library_cards` — no previews start with `![` or contain `substackcdn.com`.

---

### Step 5: (Slice 2) Enrich terse titles with one-line descriptions
**File:** Schema change to `LibraryCard` + new enrichment pass

**Problem:** Titles like "Architecture" or "Clare Sullivan" don't convey what the section covers.

**Fix:**
1. Add `description` column to `LibraryCard` (nullable text)
2. Add an enrichment pass that generates a one-line description per structural card:
   ```
   Input: title="Architecture", content="SWIFT doesn't actually move money..."
   Output: description="SWIFT message architecture: how payment instructions flow between banks"
   ```
3. Surface in `get_library_cards` output

**Why Slice 2:** LLM call per card (~50-100 × 7 collections = 350-700 calls). Defer or do lazily (generate on first `get_library_cards` access, cache in DB).

**Verify:** Terse titles have descriptions that convey the section's topic.

---

### Step 6: Regenerate existing cards (one-time cleanup)
After deploying fixes 1-4, the existing 58 topic cards still have old issues. Provide a regeneration path:

**Option A:** Delete all topic/evolution/gap cards for a collection and re-run consolidation (dedup + clamping + prompt fixes apply to the new run).

**Option B:** Add a `regenerate_topic_cards` flag to `run_collection_maintenance` that clears existing synthesized cards before re-consolidating.

**Verify:** After regeneration — no duplicate topics, no negative importance, no image-noise previews, no overloaded Miscellaneous.

---

### Files Changed Summary

| File | Change | Slice |
|---|---|---|
| `consolidation_runner.py` | `_fetch_existing_topic_labels`; pass labels into `_cluster_topics` prompt | 1 |
| `consolidation_runner.py` | Rewrite `_TOPIC_CARD_SYSTEM` importance prompt | 1 |
| `consolidation_runner.py` | Clamp importance in `_generate_topic_card` | 1 |
| `consolidation_runner.py` | Rewrite `_TOPIC_CLUSTERING_SYSTEM` (no Miscellaneous) | 1 |
| `presentation/api/tasks.py:915` | `_strip_leading_images` helper; apply to structural card content | 1 |
| `infrastructure/data/tables/library_card.py` | Add `description` column | 2 |
| New enrichment pass | LLM descriptions per card | 2 |

### Dependencies
- No new libraries (all fixes use existing tools)

### Verification Checklist

- [ ] No two topic cards in a collection are near-duplicate concepts
- [ ] All importance values in [0.0, 1.0]
- [ ] "Meta-Constitution" and "Critiques of Marxism" score >= 0.7
- [ ] Importance distribution spreads (not 88% at 0.7+)
- [ ] At most 1 Miscellaneous/Unclassified per collection
- [ ] No structural card preview contains image markdown
- [ ] Browsing `get_library_cards` shows readable, descriptive previews
- [ ] An agent can decide whether to query a document from its card alone
