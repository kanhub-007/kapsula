# Implementation Guide — Maintenance-State Canonical-Key Migration

## Slice 1

### Step 1.1: Add `_canonicalize_keys`
**File:** `kapsula/infrastructure/repositories/processing/maintenance_state_manager.py`

In `_load_states`, after parsing the JSON and before caching, run a
canonicalization pass:

```python
def _canonicalize_keys(states: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Re-key any entry whose key != its collection_id (GUID).

    Idempotent: a fully-canonical file is returned unchanged. Malformed
    entries (missing/empty collection_id) are left in place with a
    warning — never delete state we can't prove is duplicate.
    """
    canonical: dict[str, dict[str, Any]] = {}
    mutated = False
    for key, state in states.items():
        guid = state.get("collection_id") if isinstance(state, dict) else None
        if not guid:
            logger.warning(
                "maintenance state entry key=%s has no collection_id; "
                "leaving in place (cannot canonicalize)",
                key,
            )
            canonical[key] = state
            continue
        if key == guid:
            canonical[key] = state
            continue
        # Legacy DB-ID key: migrate to GUID. If a GUID entry already
        # exists (both were present), the GUID entry wins — drop the
        # legacy duplicate without overwriting.
        if guid not in canonical:
            canonical[guid] = state
        else:
            logger.info(
                "Dropping duplicate legacy maintenance state key=%s "
                "(GUID key %s already present)", key, guid,
            )
        mutated = True
    return canonical, mutated
```

### Step 1.2: Persist after migration (only if changed)
In `_load_states`, after canonicalization:
```python
if mutated:
    self._save_states(canonical)  # also sets self._cache
else:
    self._cache = canonical
```
This avoids rewriting the file on every load when it's already canonical
(idempotency, S1.3).

### Step 1.3: Keep `_deduplicate_states` for the transition
Leave it and its two call sites intact for Slice 1. It becomes a no-op
on canonicalized data but guards against any in-flight old process.

**Verify:** new `test_canonical_key_migration.py` covering S1.1–S1.5.

---

## Slice 2 (after one release window)

### Step 2.1: Delete the guard
- Remove `_deduplicate_states` and its calls in
  `mark_collection_stale` / `mark_collection_fresh`.

### Step 2.2: Audit write paths
- Confirm (via grep) every `states[...] =` uses the GUID.

**Verify:** `grep "_deduplicate_states" kapsula/` empty; full suite green.

---

## Common mistakes
- **Deleting the legacy entry before checking a GUID entry exists** —
  loses the only copy of the state. Always prefer the GUID-keyed entry
  when both exist (S1.2).
- **Rewriting the file on every load** — burns disk on hot paths. Only
  persist when `mutated` (S1.3).
- **Raising on malformed entries** — a corrupt file must not crash the
  whole manager; log and carry on (S1.4).
- **Running the migration outside the lock** — must hold `_STATE_LOCK`
  so two threads don't double-migrate.
