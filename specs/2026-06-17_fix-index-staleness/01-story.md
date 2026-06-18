# Fix Aggregate Index Staleness

## User Story
As a kapsula user, I want `run_collection_maintenance` to correctly clear the `collection_index_stale` flag after rebuilding indexes, so that `list_stale_maintenance` reflects the true state and I don't waste time re-running maintenance on already-fresh collections.

## Context

Two bugs cause `collection_index_stale` to remain `True` after maintenance completes, even though the FAISS+BM25 indexes exist and are up-to-date on disk.

### Bug 1: `AggregateIndexBuilder` returns `(None, None)` for fully-indexed collections

In `_build_from_docs`, when the incremental path detects that all chunks are already indexed (their content hashes all exist in `existing_hashes`), the `_collect_texts_and_mapping` function skips every chunk. `all_texts` ends up empty. The early guard `if not all_texts: return None, None` fires BEFORE the incremental reuse logic that would have returned the existing index paths.

The result: `_rebuild_aggregate_indexes` receives `(None, None)`, sets `collection_index_updated = False`, and `mark_collection_fresh(collection, collection_index=False)` does not clear the stale flag.

### Bug 2: `MaintenanceStateManager` creates duplicate entries with different keys

- `increment_uploads` uses the **collection GUID** as the state key → creates entries with `collection_db_id: null`
- `mark_collection_stale` / `mark_collection_fresh` use `str(collection.id)` (the **DB integer ID**) as the key
- Both entries persist in `maintenance_state.json` and both appear in `list_stale()`

After maintenance, the DB-ID-keyed entry may still show stale if Bug 1 prevents the flag from being cleared. The GUID-keyed entry always shows fresh (it was never marked stale to begin with).

## Non-Goals
- Changing the incremental indexing strategy (chunk hash dedup is correct, just the early return is wrong)
- Migrating existing stale state entries (will be cleaned up by the next maintenance run)
- Making `_collect_texts_and_mapping` always collect all texts (incremental dedup is desirable for performance)
