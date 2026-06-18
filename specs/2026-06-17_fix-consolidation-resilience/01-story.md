# Fix Consolidation Resilience

## User Story
As a kapsula user running collection maintenance, I want consolidation to complete reliably — without truncated LLM output causing silent zero-card failures, and without DB lock cascades losing generated topic cards — so that every collection gets properly synthesized topic cards on the first attempt.

## Context

Two bugs combine to make consolidation unreliable. Both were observed in production logs during maintenance of the escapekey corpus (536 articles across 7 collections).

### Bug 1: Truncated LLM output (`max_tokens=1000`)

`_cluster_topics` sends up to 100 H2/H3 extractive cards (each with a 200-char preview) to the LLM and asks it to group them into topics. The response is a JSON object containing a `topics` array, where each topic has `label`, `card_ids[]`, and `rationale`. With 100 cards clustered into 7+ topics, the output easily exceeds 1000 tokens. The LLM response gets truncated mid-array:

```
"card_ids": [16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 29, 30, ...
                                                                       ^ cut off
```

`_parse_json_safely` (hardened earlier) gracefully returns `{}` on the truncated JSON. Then `plan.get("topics", [])` returns `[]` → `clusters = []` → consolidation runs to completion but produces **zero cards**, silently succeeding with nothing to show. The failure is invisible unless you check `get_consolidation_status` and see `Topic cards: 0`.

**Verified:** Tested with the actual truncated output from the logs — `_parse_json_safely` returns `{}` → `topics count: 0`.

### Bug 2: SQLite write contention — no busy_timeout, poisoned session cascade

WAL mode is enabled (good for concurrent reads), but WAL still serializes **writers** — only one writer holds the lock at a time. The connection has **no `busy_timeout`** set (SQLite default is 0ms), so a second writer fails **immediately** instead of waiting.

When two consolidations run in parallel background threads:

1. Thread A acquires the write lock, inserts topic cards
2. Thread B tries to insert → `database is locked` (fails instantly, no wait)
3. Thread B's SQLAlchemy session enters a `PendingRollbackError` state
4. The per-card `except` block in `_generate_topic_card` logs the error but **does not call `session.rollback()`** — the session stays poisoned
5. Every subsequent `_generate_topic_card` call fails on the poisoned session (`PendingRollbackError`)
6. `_record_run(error=None)` at the end also fails on the poisoned session
7. The outer `except` tries `_record_run(error=str(exc))` — **also fails** (session still poisoned)
8. `collection_maintenance_runner.py` catches the exception and accesses `collection.collection_id` → triggers a lazy load on the poisoned session → fails **again**

The result: **all topic cards from Thread B are lost**, even though the LLM correctly generated them. The cascade produces a wall of identical-looking errors in the logs.

The root causes:
- **No `busy_timeout`** — SQLite fails immediately instead of waiting for the lock to clear (verified: with `busy_timeout=5000`, a second writer waits ~1.5s and succeeds)
- **No `session.rollback()` in error handlers** — after any flush/commit exception, the session MUST be rolled back before further use (SQLAlchemy requirement; the `PendingRollbackError` message literally instructs this)

**Verified:** Tested `busy_timeout` with two threads — Thread 2 waited 1.53s and succeeded. Tested session poisoning pattern — confirms standard SQLAlchemy behavior requiring `rollback()`.

## Non-Goals
- Switching LLM output format from JSON to YAML (separate spec: `2026-06-17_yaml-llm-output`)
- Changing SQLite to PostgreSQL (out of scope)
- Parallel consolidation execution (the fixes make it safe, but serialization remains acceptable)
- Rewriting the consolidation prompt strategy (topic clustering logic stays the same)
- Removing the incremental index pattern (hash-based dedup is correct)
