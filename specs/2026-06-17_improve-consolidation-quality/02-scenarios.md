# Scenarios — Improve Consolidation Quality

---

### Scenario: Near-duplicate topic clusters are merged via prompt-based dedup
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a collection already has a topic card titled "Financial & Digital Control Infrastructure"
  When  a subsequent consolidation run clusters cards and produces a similar group
  Then  the clustering prompt includes the existing topic labels
  And   the LLM reuses "Financial & Digital Control Infrastructure" rather than inventing "Financial Surveillance & Control Infrastructure"
  And   no near-duplicate topic card is created

**Input table:**
| Field              | Type   | Example                                     | Constraints                  |
|--------------------|--------|---------------------------------------------|------------------------------|
| existing_labels    | list   | ["Financial & Digital Control Infrastructure", "Central Banking Architecture"] | From current topic cards |
| new_cards          | list   | 50 H2/H3 extractive cards                   | From `_gather_extractive_cards` |

**Expected output:**
| Assertion                         | How to verify                     |
|-----------------------------------|-----------------------------------|
| No two topic labels are semantically near-duplicate | Manual review + spot-check |
| Existing labels reused when applicable | Compare new labels to existing — no new near-dupes |

**Verify (Classical school, black-box):**
```python
# Run consolidation twice on the same collection
run_collection_maintenance(coll_id)
wait_for_completion()
topics_before = get_topic_labels(coll_id)

run_collection_maintenance(coll_id)  # second run
wait_for_completion()
topics_after = get_topic_labels(coll_id)

# Second run should not add near-duplicate labels
assert len(topics_after) <= len(topics_before) + 1  # allow 1 genuinely new topic
# Manual check: no two labels describe the same concept
```

**Also test:**
- First-ever consolidation (no existing labels) — should still produce 3-8 clean topics
- Genuinely new content added — should create a new topic, not force-fit into existing

---

### Scenario: Importance scores are clamped to valid range
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the LLM returns `importance: -1.0` or `importance: 1.5`
  When  the topic card is stored
  Then  importance is clamped to `[0.0, 1.0]`
  And   no negative or >1 values persist

**Input table:**
| Field       | Type  | Example | Constraints        |
|-------------|-------|---------|--------------------|
| importance  | float | -1.0    | LLM output, any    |

**Expected output:**
| Assertion                         | How to verify                     |
|-----------------------------------|-----------------------------------|
| Stored value in [0.0, 1.0]        | Query all topic cards             |

**Verify:**
```python
topics = db.query(LibraryCard).filter_by(card_type="topic").all()
for t in topics:
    assert 0.0 <= t.importance <= 1.0, f"{t.title}: importance={t.importance}"
```

---

### Scenario: Importance prompt grounds the scale in centrality, not vague "facts"
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the updated `_TOPIC_CARD_SYSTEM` prompt
  When  the LLM assigns importance to a topic card
  Then  the scale is defined as centrality to the argument (foundational → contextual)
  And   the prompt explicitly forbids negative values
  And   the previously-negative cards ("Meta-Constitution", "Critiques of Marxism") score high (they're foundational)

**Input table:**
| Field       | Type   | Example                              | Constraints        |
|-------------|--------|--------------------------------------|--------------------|
| topic_label | string | "The Meta-Constitution & Rule-Based Enforcement" | — |
| sections    | list   | The cluster's source card contents   | — |

**Expected output:**
| Assertion                         | How to verify                     |
|-----------------------------------|-----------------------------------|
| "Meta-Constitution" scores >= 0.8 | It's foundational to the argument |
| Distribution spreads across the range | Not 88% bunched at 0.7+ |

**Verify:**
```python
assert "centrality" in _TOPIC_CARD_SYSTEM.lower() or "foundational" in _TOPIC_CARD_SYSTEM.lower()
assert "never return negative" in _TOPIC_CARD_SYSTEM.lower()
# After re-consolidation:
meta = db.query(LibraryCard).filter_by(title="The Meta-Constitution & Rule-Based Enforcement").first()
assert meta.importance >= 0.7  # foundational, not hidden
```

---

### Scenario: Clustering prompt discourages Miscellaneous overuse
**Priority:** Should
**Slice:** 1

**Gherkin:**
  Given the updated `_TOPIC_CLUSTERING_SYSTEM` prompt
  When  the LLM clusters cards
  Then  it creates specific topic groups (3-8) rather than defaulting to Miscellaneous
  And   Miscellaneous is only created when a card truly fits no other group

**Input table:**
| Field       | Type   | Example                  | Constraints       |
|-------------|--------|--------------------------|-------------------|
| cards       | list   | 50 H2/H3 extractive cards| From gather step  |

**Expected output:**
| Assertion                         | How to verify                     |
|-----------------------------------|-----------------------------------|
| At most 1 Miscellaneous per collection | Query topic cards           |

**Verify:**
```python
assert "avoid" in _TOPIC_CLUSTERING_SYSTEM.lower() or "specific" in _TOPIC_CLUSTERING_SYSTEM.lower()
misc = db.query(LibraryCard).filter_by(
    collection_id=cid, card_type="topic", title="Miscellaneous"
).count()
assert misc <= 1
```

---

### Scenario: Structural card previews strip image markdown
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a document chunk whose content begins with `![alt](https://substackcdn.com/...)`
  When  a library card is generated from that chunk
  Then  the card's preview excludes image markdown
  And   the preview shows actual descriptive text from the section

**Input:**
| Field       | Type   | Example                                                                              |
|-------------|--------|--------------------------------------------------------------------------------------|
| raw_content | string | `![esc's avatar](https://substackcdn.com/...)\n\nThe BIS acts as the central bank...` |

**Expected preview:**
```
The BIS acts as the central bank of central banks...
```

**Verify:**
```python
cards = db.query(LibraryCard).filter_by(card_type="extractive").all()
for card in cards:
    preview = card.content[:200]
    assert "![" not in preview, f"{card.title}: preview contains image markdown"
    assert "substackcdn.com" not in preview
```

**Note:** This fix targets structural cards only. The search index (chunks) is already clean — the chunker strips images. Only the card `content` field (created at `tasks.py:915`) retains them.

---

### Scenario: Structural cards include a one-line section description (Slice 2)
**Priority:** Could
**Slice:** 2

**Gherkin:**
  Given a terse heading like "Architecture" or "Clare Sullivan"
  When  the library card is generated
  Then  the card includes a generated one-line description of what the section covers
  And   the description helps an agent decide whether to query without reading the document

**Input table:**
| Field       | Type   | Example                                                        |
|-------------|--------|----------------------------------------------------------------|
| title       | string | "Architecture"                                                 |
| content     | string | "SWIFT doesn't actually move money. It moves information..."   |

**Expected output:**
| Field        | Example                                                        |
|--------------|----------------------------------------------------------------|
| description  | "SWIFT message architecture: how payment instructions flow"   |

**Verify:**
```python
cards = db.query(LibraryCard).filter_by(card_type="extractive", level="level_2").all()
for card in cards:
    assert card.description, f"{card.title}: no description"
    assert len(card.description) > 20, f"{card.title}: description too short"
```

**Note:** Requires an LLM pass per card (~50-100 cards × 7 collections). Expensive. Defer or do lazily on first access.
