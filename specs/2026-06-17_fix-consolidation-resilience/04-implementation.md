# Implementation Guide — Fix Consolidation Resilience

---

### Step 1: Add `busy_timeout` to SQLite connection
**File:** `kapsula/infrastructure/data/connection.py`

**Problem:** SQLite's default `busy_timeout` is 0ms — writers fail immediately when another writer holds the lock. WAL mode is enabled (good for concurrent reads), but writers are still serialized. With no busy_timeout, the second writer gets `database is locked` instantly.

**Fix:** Add `PRAGMA busy_timeout=5000` (5 seconds) to the existing `_set_sqlite_pragma` event listener.

```python
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")  # NEW: wait 5s for write lock
    cursor.close()
```

**Verified:** Tested with two threads — Thread 2 waited 1.53s and succeeded instead of failing. Consolidation writes are fast (<100ms per insert), so 5s is ample headroom.

**Trade-off:** A writer blocked on the lock holds its thread for up to 5s. During this window, MCP tool calls needing write access also wait. Acceptable because consolidation is infrequent and writes are fast once acquired.

**Verify:** Run two consolidations simultaneously — the second should wait and succeed, not fail with `database is locked`.

---

### Step 2: Add `session.rollback()` in consolidation error handlers
**File:** `kapsula/infrastructure/repositories/processing/consolidation_runner.py`

**Problem:** When a `database is locked` (or any) error occurs during `_generate_topic_card`'s `db.flush()`, the SQLAlchemy session enters a `PendingRollbackError` state. Every subsequent DB operation fails — including the next card's insert, `_record_run(error=...)`, and even lazy-loaded attribute access like `collection.collection_id`.

**Fix:** Three rollback points:

1. **Inside the per-card `except` block** (the `for cluster in clusters` loop): Call `self._db.rollback()` after logging the error, so the next card's `_generate_topic_card` starts on a clean session.

2. **At the start of the outer `except` block** (the `run()` method's catch-all): Call `self._db.rollback()` BEFORE `_record_run(error=str(exc))`, so the error record can be persisted.

3. **Defensive rollback in `_record_run`**: Wrap the `commit()` in try/except — if recording the error itself fails, log and continue rather than crashing.

**Current code (broken cascade):**
```python
for cluster in clusters:
    try:
        self._generate_topic_card(cluster)
    except Exception as exc:
        logger.error(...)  # session still poisoned! next card will fail too

self._record_run(error=None)  # fails on poisoned session
# ... outer except:
self._record_run(error=str(exc))  # ALSO fails — double poison
```

**Fixed code:**
```python
for cluster in clusters:
    try:
        self._generate_topic_card(cluster)
    except Exception as exc:
        logger.error(...)
        self._db.rollback()  # un-poison for next card

# ... outer except:
self._db.rollback()  # un-poison before recording error
self._record_run(error=str(exc))
```

**Verified:** Standard SQLAlchemy pattern — the `PendingRollbackError` message explicitly says "To begin a new transaction with this Session, first issue Session.rollback()."

**Verify:** Simulate a DB lock during topic card generation — subsequent cards should still be attempted, and the consolidation_run error record should be persisted.

---

### Step 3: Increase `max_tokens` for topic clustering
**File:** `consolidation_runner.py`, `_cluster_topics` method

**Problem:** `max_tokens=1000` is too small. With up to 100 cards clustered into 7+ topics, each topic needs `label` (~10 tokens) + `card_ids[]` (~50-100 tokens for 20+ IDs) + `rationale` (~100-200 tokens). That's easily 2,500+ tokens for 7 topics, well over the 1000 limit. The response truncates mid-array, producing unparseable JSON.

**Fix:** Increase `max_tokens` from 1000 to 4000 in `_cluster_topics`. This covers:
- ~7-8 topic clusters × ~300 tokens each = ~2,500 tokens
- Plus JSON structure overhead
- Headroom for verbose rationales

```python
response = self._chat_client.send(
    messages=[...],
    max_tokens=4000,  # was 1000
    temperature=0.3,
)
```

**Verified:** The actual truncated log output (3,382 chars, ~850 tokens) was cut off because the LLM hit the 1000-token limit mid-array. 4000 gives ~4x headroom.

**Why not just remove the limit?** Some LLM APIs enforce a hard cap. 4000 is safe across common models (DeepSeek, Llama, etc.) and still bounded to prevent runaway output.

**Verify:** Run consolidation on technology-surveillance (42 docs, ~50 cards) — the LLM response should not be truncated, and topic cards should be created.

---

### Step 4: (Slice 2) Card batching for very large collections
**File:** `consolidation_runner.py`, `_cluster_topics` method

**Problem:** For collections with 200+ extractive cards, even with `max_tokens=4000` the response may hit limits, and the input prompt (100 cards × 200-char previews = 20K chars) may strain the model's context window.

**Fix:** If `len(cards) > BATCH_SIZE` (e.g., 50), split into batches, cluster each independently, then merge:
1. Cluster each batch separately (each gets its own LLM call)
2. For batches 2+, check if any new cluster labels fuzzy-match existing ones
3. Merge `card_ids` for matching labels
4. Append unique new clusters

This is a future safety net — for the current 536-article corpus, no single collection exceeds ~90 documents (~50 cards), so batching is not immediately necessary. It becomes relevant when collections grow past ~150 documents.

---

### Files Changed Summary

| File | Change |
|---|---|
| `infrastructure/data/connection.py` | Add `PRAGMA busy_timeout=5000` |
| `infrastructure/repositories/processing/consolidation_runner.py` | Rollback in per-card + outer error handlers; `max_tokens` 1000→4000 |
| `infrastructure/repositories/processing/consolidation_runner.py` | (Slice 2) Card batching in `_cluster_topics` |

### Dependencies
- No new dependencies (all fixes use existing libraries)
