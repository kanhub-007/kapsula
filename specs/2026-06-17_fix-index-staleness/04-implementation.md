# Implementation Guide — Fix Aggregate Index Staleness

---

### Step 1: Fix `_build_from_docs` early return for fully-indexed collections
**File:** `kapsula/infrastructure/repositories/indexing/aggregate_index_builder.py`

The bug: `if not all_texts: return None, None` fires before the incremental reuse logic when all chunks are already indexed.

The fix: when `all_texts` is empty but the existing mapping and index files exist on disk, return the existing paths instead of None.

```python
# In _build_from_docs, replace:
if not all_texts:
    return None, None

# With:
if not all_texts:
    # All chunks already indexed — return existing paths if they exist
    if os.path.exists(paths.faiss) and os.path.exists(paths.bm25):
        logger.info(
            "All %s chunks for %s already indexed; reusing existing indexes",
            len(existing_mapping),
            label,
        )
        return paths.faiss, paths.bm25
    return None, None
```

**Verify:** Call `builder.build()` on the health-biosecurity collection — should return non-None paths.

**Common mistake:** Only checking `paths.faiss` — must check both `.faiss` and `.bm25`.

---

### Step 2: Fix `MaintenanceStateManager` duplicate key bug
**File:** `kapsula/presentation/upload/maintenance_state_manager.py`

The bug: `increment_uploads` creates entries keyed by collection GUID, while `mark_collection_stale` and `mark_collection_fresh` use `str(collection.id)` (DB integer ID). Both persist and both appear in `list_stale()`.

The fix: normalize all methods to use the collection GUID as the key. The GUID is the natural identifier (used everywhere else in the system) and `increment_uploads` only receives the GUID (not the DB ID).

```python
# In mark_collection_stale, change:
key = str(collection.id)
# To:
key = collection.collection_id

# In mark_collection_fresh, change:
key = str(collection.id)
# To:
key = collection.collection_id
```

Also update `_new_state` to set `collection_db_id` from `collection.id` so it's preserved:

```python
@staticmethod
def _new_state(collection: Collection) -> dict[str, Any]:
    return {
        "collection_db_id": collection.id,  # already correct, verify
        "collection_id": collection.collection_id,
        ...
    }
```

Under `increment_uploads`, when creating a new entry (no existing state found), the GUID is already used as key — that's correct. Ensure `collection_db_id` is left as `None` for GUID-only entries (acceptable — the DB ID can be resolved when needed).

**Verify:** After maintenance completes, `_load_states()` has exactly one entry per collection (keyed by GUID), and `collection_index_stale: false` for all.

**Common mistake:** Don't change `increment_uploads` — it already uses GUIDs. Only `mark_collection_stale` and `mark_collection_fresh` need fixing.

---

### Step 3: Clean up existing duplicate entries (one-time)
**File:** `kapsula/presentation/upload/maintenance_state_manager.py`

Add a migration method or run a one-time cleanup after the key fix. The simplest approach: on next `mark_collection_fresh` or `mark_collection_stale`, remove any entries keyed by DB integer ID that have a corresponding GUID-keyed entry.

```python
# In mark_collection_fresh and mark_collection_stale, after updating the GUID-keyed entry:
def _deduplicate_states(self, states: dict, collection: Collection) -> None:
    """Remove stale entries keyed by DB integer ID for this collection."""
    guid_key = collection.collection_id
    for key in list(states.keys()):
        state = states.get(key)
        if state and key != guid_key and state.get("collection_id") == guid_key:
            del states[key]
            logger.info("Removed duplicate maintenance state key=%s for collection %s", key, guid_key)
```

**Verify:** After all collections complete maintenance, `maintenance_state.json` has exactly 7 entries (one per collection), all keyed by GUID.

---

### Verification Checklist

- [ ] `builder.build()` returns non-None paths for fully-indexed collections
- [ ] `collection_index_stale` cleared after maintenance on health-biosecurity
- [ ] `collection_index_stale` cleared after maintenance on climate-planetary-governance
- [ ] `maintenance_state.json` has no duplicate entries
- [ ] `list_stale_maintenance` returns empty after all collections maintained
- [ ] Empty collections still return `(None, None)` gracefully
