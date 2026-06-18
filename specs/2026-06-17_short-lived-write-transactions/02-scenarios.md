# Scenarios — Short-Lived Write Transactions in Consolidation

---

### Scenario: LLM call happens outside any open write transaction
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a consolidation run with multiple topic clusters to process
  When  `_generate_topic_card` is called for a cluster
  Then  the `chat_client.send()` call completes BEFORE any DB write begins
  And   no write transaction is held open during the LLM network call
  And   the DB write (upsert + references) is committed immediately after

**Verify (Classical school, black-box):**
```python
# Instrument the chat client to record whether a transaction is open
call_during_txn = []
original_send = runner._chat_client.send
def spy_send(*args, **kwargs):
    in_txn = runner._db.in_transaction()
    call_during_txn.append(in_txn)
    return original_send(*args, **kwargs)
runner._chat_client.send = spy_send

runner.run()
assert not any(call_during_txn), "LLM calls happened inside an open transaction"
```

---

### Scenario: Two concurrent consolidations interleave without DB lock errors
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given two collections with pending consolidation
  When  both maintenance jobs run concurrently in background threads
  Then  both complete successfully
  And   neither produces a `database is locked` error
  And   both collections have their full set of topic cards

**Verify:**
```python
# Start both jobs concurrently
job1 = run_collection_maintenance(coll_a)
job2 = run_collection_maintenance(coll_b)
# Poll until both complete
wait_for_completion([job1, job2])
assert get_maintenance_job(job1).status == "completed"
assert get_maintenance_job(job2).status == "completed"
assert get_maintenance_job(job1).error is None
assert get_maintenance_job(job2).error is None
# Both have topic cards
assert get_consolidation_status(coll_a).topic_count > 0
assert get_consolidation_status(coll_b).topic_count > 0
```

---

### Scenario: Partial failure does not corrupt committed topic cards
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a consolidation run processing 7 topic clusters
  When  cluster #4 fails (e.g., LLM returns unparseable output)
  Then  clusters #1-3 are already committed and persisted
  And   clusters #5-7 are still attempted
  And   the consolidation_run record reflects the partial result (cards_created=6, error noted)

**Verify:**
```python
# Mock cluster #4's LLM response to be garbage
runner._chat_client.send = respond_garbage_on_fourth_call
result = runner.run()
# 6 of 7 cards committed
cards = db.query(LibraryCard).filter_by(collection_id=cid, card_type="topic").all()
assert len(cards) == 6
run = db.query(ConsolidationRun).filter_by(collection_id=guid).order_by(
    ConsolidationRun.created_at.desc()
).first()
assert run.cards_created == 6
```

---

### Scenario: Write transaction held only for the DB write, not the LLM call
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given instrumentation measuring write-lock hold time
  When  consolidation runs
  Then  the cumulative time the write lock is held is < 1% of total run time
  And   no single write-lock hold exceeds 100ms

**Verify:**
```python
# Instrument the connection to time BEGIN..COMMIT spans
lock_holds = []  # list of (start, end) tuples
# ... instrument sqlite connection events ...
runner.run()
durations = [(e - s).total_seconds() for s, e in lock_holds]
assert max(durations) < 0.1, f"Max lock hold {max(durations)}s > 100ms"
```

---

### Scenario: Consolidation run record persists even if all topic cards fail
**Priority:** Should
**Slice:** 1

**Gherkin:**
  Given every `_generate_topic_card` raises an exception
  When  consolidation completes (with all per-card failures caught)
  Then  the consolidation_run row is committed with error recorded
  And   cards_created=0

**Verify:**
```python
runner._chat_client.send = always_raises
result = runner.run()
run = db.query(ConsolidationRun).filter_by(collection_id=guid).order_by(
    ConsolidationRun.created_at.desc()
).first()
assert run is not None
assert run.cards_created == 0
assert run.error is not None
```
