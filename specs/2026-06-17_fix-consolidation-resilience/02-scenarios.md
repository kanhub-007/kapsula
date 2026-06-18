# Scenarios — Fix Consolidation Resilience

---

### Scenario: Large collection topic clustering succeeds without truncation
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a collection with 50+ extractive H2/H3 cards (e.g., technology-surveillance, 42 docs)
  When  consolidation's `_cluster_topics` is called
  Then  the LLM response is NOT truncated mid-output
  And   valid topic clusters (3-8) are returned
  And   topic cards are generated for every cluster

**Input table:**
| Field            | Type | Example                  |
|------------------|------|--------------------------|
| extractive_cards | list | 50-100 LibraryCard rows  |

**Expected output:**
| Assertion                         | How to verify                     |
|-----------------------------------|-----------------------------------|
| clusters list has 3-8 entries     | `len(clusters) >= 3`             |
| Each cluster has valid label      | `cluster["label"]` is non-empty  |
| Topic cards created               | `cards_created >= len(clusters)` |

**Verify (Classical school, black-box):**
```python
cards = runner._gather_extractive_cards()
assert len(cards) > 30  # large collection
clusters = runner._cluster_topics(cards)
assert len(clusters) >= 3
assert all(c.get("label") for c in clusters)
assert all(len(c.get("_cards", [])) > 0 for c in clusters)
```

**Also test:**
- Collection with exactly 100 cards (boundary of the `[:100]` limit)
- Collection with 5 cards (small — should still cluster correctly)

---

### Scenario: SQLite write contention is resolved with busy_timeout
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given two consolidation jobs attempt to write to the same SQLite database simultaneously
  When  the second job tries to insert while the first holds the lock
  Then  SQLite waits up to `busy_timeout` ms instead of failing immediately
  And   the second job's write succeeds once the first releases the lock

**Verify:**
```python
# Check that busy_timeout is set in connection.py
from kapsula.infrastructure.data.connection import engine
conn = engine.raw_connection()
cursor = conn.cursor()
cursor.execute("PRAGMA busy_timeout")
result = cursor.fetchone()[0]
assert result > 0, f"busy_timeout is {result}, expected > 0"
conn.close()
```

**Also test:**
- Two concurrent writers — both should eventually succeed (one waits, one proceeds)
- Writer holds lock longer than `busy_timeout` — second writer fails with `database is locked` (acceptable, but should be rare)

---

### Scenario: Session rollback prevents cascading failures after lock error
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a consolidation job encounters a `database is locked` error during topic card insertion
  When  the per-card error handler catches the exception
  Then  `self._db.rollback()` is called before continuing to the next card
  And   subsequent topic card insertions can proceed on a clean session
  And   the consolidation_run record is persisted (with or without error)

**Verify:**
```python
# Simulate: _generate_topic_card #1 hits a lock, rolls back,
# then _generate_topic_card #2 succeeds on the fresh session
assert runner._cards_created >= 1  # At least one card survived
# The consolidation_run row exists regardless of partial failures
runs = db.query(ConsolidationRun).filter_by(collection_id=guid).all()
assert len(runs) >= 1
```

**Also test:**
- All topic cards fail — consolidation_run is still recorded with error message
- First card fails, second succeeds — both outcomes are logged, run completes

---

### Scenario: Consolidation run record always persisted, even on total failure
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a consolidation job fails completely (e.g., LLM API down, all cards fail)
  When  the outer exception handler runs
  Then  `self._db.rollback()` is called first to un-poison the session
  And   `_record_run(error=str(exc))` succeeds on the clean session
  And   the consolidation_run row records the error for debugging

**Verify:**
```python
# Force a total failure (e.g., mock chat_client.send to raise)
runner._chat_client.send = mock_that_raises
result = runner.run()
assert result is not None  # didn't crash
runs = db.query(ConsolidationRun).filter_by(collection_id=guid).order_by(ConsolidationRun.created_at.desc()).all()
assert runs[0].error is not None  # error recorded
```

---

### Scenario: Card batching handles collections larger than prompt window
**Priority:** Could
**Slice:** 2

**Gherkin:**
  Given a collection with 200+ extractive cards (exceeding a single LLM prompt even with max_tokens=4000)
  When  `_cluster_topics` is called
  Then  cards are split into batches of ~50
  And   each batch is clustered independently
  And   results are merged (deduplicating similar topic labels)

**Verify:**
```python
cards = [...] # 200 cards
clusters = runner._cluster_topics(cards)
# Should handle batching internally
assert len(clusters) >= 3
```
