# Short-Lived Write Transactions in Consolidation

## User Story
As a kapsula maintainer, I want consolidation to hold SQLite write transactions only for brief DB writes — not across long LLM network calls — so that parallel maintenance jobs can run concurrently without `database is locked` errors.

## Context

### Current design: one transaction, commit at the very end

`ConsolidationRunner.run()` opens a SQLAlchemy session at the start and only commits at the very end via `_record_run()`. Between those points, every step holds the transaction open:

```
ConsolidationRunner.run():
    cards = self._db.query(...)              ← transaction opened
    for cluster in clusters:
        response = chat_client.send(...)     ← 30-60s LLM call (txn OPEN, idle)
        self._db.flush()                     ← write (txn still OPEN)
        ...
    self._db.commit()                        ← commits EVERYTHING at end
```

The same pattern holds for `_generate_evolution_card` and `_generate_gap_cards` — each does an LLM call then a write, all under one uncommitted transaction.

### Why this breaks concurrency

SQLite serializes writers. With WAL mode + `busy_timeout=5000`:
- A **short** writer (fast INSERT) waits ≤5s for the lock and succeeds
- A **long** writer (holding the lock across a 60s LLM call) exceeds `busy_timeout` — the second writer fails with `database is locked` after 5s

`busy_timeout` only helps when write locks are held briefly. Consolidation holds the lock for **minutes** (multiple LLM calls per run), so no reasonable `busy_timeout` can paper over it.

### Workaround in place (Option A)

A module-level `threading.Lock` in `maintenance_runner.py` serializes maintenance jobs — only one runs at a time, others queue with `status="queued"`. This is correct and robust but means 7 collections take ~7× the time of one.

### Target design: commit after each logical unit

The fix is to make write transactions short-lived. Each `_generate_topic_card`, `_generate_evolution_card`, and `_generate_gap_cards` should:
1. Do the LLM call **outside** any DB transaction
2. Open a transaction, write the result, commit immediately
3. Release the lock before the next LLM call

This way the SQLite write lock is held only for the brief DB write (~ms), not the LLM call (~seconds/minutes). Parallel consolidations interleave their LLM calls and briefly contend only on the fast writes — which `busy_timeout=5000` handles easily.

## Non-Goals
- Removing the Option A serialization lock (keep it as a belt-and-suspenders safety net even after this fix)
- Changing the consolidation prompts or topic-clustering logic
- Making reads transactional (reads already work fine with WAL)
- Switching to PostgreSQL (out of scope)
