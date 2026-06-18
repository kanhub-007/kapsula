# Implementation Guide — Short-Lived Write Transactions in Consolidation

---

### Step 1: Inject a session factory instead of a session
**File:** `kapsula/infrastructure/repositories/processing/consolidation_runner.py`

**Problem:** `ConsolidationRunner.__init__` takes a `db: Session` and holds it open for the entire run. All LLM calls happen inside that session's transaction.

**Fix:** Inject `session_factory: Callable[[], Session]` instead. Each write step creates a fresh session, writes, commits, and closes. The session is never held across an LLM call.

```python
class ConsolidationRunner:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        chat_client: ChatClient,
        collection_id: int,
        collection_guid: str,
    ):
        self._session_factory = session_factory
        # ...
```

**Migration note:** `CollectionMaintenanceRunner` currently does `ConsolidationRunner(self._db, ...)`. Change to pass `SessionLocal` (the factory). Existing call sites that pass a session need updating — but the consolidation runner is the only caller.

**Verify:** Unit test constructs runner with an in-memory SQLite session factory; confirms writes are isolated per-call.

---

### Step 2: Read cards in a short transaction
**File:** `consolidation_runner.py`, `_gather_extractive_cards`

**Problem:** Currently opens the shared session, queries cards, and the ORM objects stay bound to that long-lived session.

**Fix:** Query in a short session, detach the objects, close the session:

```python
def _gather_extractive_cards(self) -> list[LibraryCard]:
    session = self._session_factory()
    try:
        cards = (
            session.query(LibraryCard)
            .filter(...)
            .order_by(LibraryCard.title)
            .all()
        )
        for card in cards:
            session.expunge(card)  # detach from session
        return cards
    finally:
        session.close()
```

**Why expunge:** The cards are used later to build LLM prompts. They must not be bound to a session (or lazy-loaded attributes like `card.document.filename` would trigger DB access on a closed session). Detaching makes them plain data holders.

**Verify:** After `_gather_extractive_cards`, `card.document` access works without a session (requires eager loading of the document relationship in the query — use `joinedload`).

---

### Step 3: Commit after each topic card
**File:** `consolidation_runner.py`, `_generate_topic_card`

**Problem:** Upserts topic cards + references under the shared session, committed only at the very end.

**Fix:** Open a fresh session, do the upsert + reference inserts, commit, close. The LLM call happens BEFORE the session opens:

```python
def _generate_topic_card(self, cluster: dict) -> None:
    source_cards = cluster.get("_cards", [])
    if not source_cards:
        return

    # LLM call — NO session open
    response = self._chat_client.send(...)
    result = _parse_json_safely(response)
    contradictions = result.get("contradictions", [])
    self._conflicts_found += len(contradictions)

    # DB write — short transaction
    session = self._session_factory()
    try:
        existing = session.query(LibraryCard).filter(...).first()
        if existing:
            existing.content = result.get("summary", "")
            # ... update fields ...
            card = existing
            self._cards_updated += 1
        else:
            card = LibraryCard(...)
            session.add(card)
            session.flush()  # get card.id
            self._cards_created += 1

        for source in source_cards:
            session.add(CardReference(source_card_id=card.id, ...))

        if contradictions:
            card.extra_metadata = json.dumps({"contradictions": contradictions})

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

**Verify:** Instrument the session — confirm `in_transaction()` is False during `chat_client.send()`.

---

### Step 4: Apply the same pattern to evolution and gap card generation
**Files:** `_generate_evolution_card`, `_generate_gap_cards`

Both currently mix LLM calls and DB writes under one session. Apply the same structure:
1. LLM call outside any session
2. Short session for the write, commit, close

`_generate_gap_cards` is slightly different — it reads `SearchMissLog` then calls the LLM then writes gap cards. Split into: read (short session) → LLM call (no session) → write (short session).

**Verify:** Each method commits independently; failures in one don't roll back the others.

---

### Step 5: Record the consolidation run in a short transaction
**File:** `consolidation_runner.py`, `_record_run`

**Problem:** Currently `_record_run` uses the shared session's `commit()`, which commits everything accumulated during the run.

**Fix:** Open a fresh session, add the `ConsolidationRun` row, commit, close:

```python
def _record_run(self, error: str | None) -> None:
    session = self._session_factory()
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
        logger.error("Failed to record consolidation run %s: %s", self._run_id, exc)
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        session.close()
```

**Verify:** `ConsolidationRun` row is persisted even if the count tracking was done across many short transactions.

---

### Step 6: Update the caller (CollectionMaintenanceRunner)
**File:** `kapsula/presentation/upload/collection_maintenance_runner.py`

Change the consolidation construction to pass the factory:

```python
# Before
runner = ConsolidationRunner(self._db, chat_client, collection.id, collection.collection_id)

# After
from kapsula.infrastructure.data import SessionLocal
runner = ConsolidationRunner(SessionLocal, chat_client, collection.id, collection.collection_id)
```

**Verify:** Consolidation still produces the same topic cards; the only observable change is transaction timing.

---

### Files Changed Summary

| File | Change |
|---|---|
| `consolidation_runner.py` | Inject `session_factory`; short-lived transactions in every method |
| `collection_maintenance_runner.py` | Pass `SessionLocal` instead of the session |

### Keep the serialization lock (Option A)

Even after this fix, keep the module-level `_maintenance_lock` in `maintenance_runner.py`. It's a cheap safety net: if some future change reintroduces a long-held transaction, the lock prevents the cascade rather than letting it surface as cryptic DB errors. The two fixes are complementary, not alternatives.

---

### Verification Checklist

- [ ] No LLM call occurs inside an open transaction (instrumented test)
- [ ] Two concurrent consolidations both complete with all topic cards
- [ ] Partial failure (cluster 4 of 7 fails) commits clusters 1-3 and 5-7
- [ ] Each write-lock hold is < 100ms
- [ ] `consolidation_run` row persisted even on total failure
- [ ] Topic card counts and references match pre-fix behavior
