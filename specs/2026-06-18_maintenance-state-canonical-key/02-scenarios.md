# Scenarios — Maintenance-State Canonical-Key Migration

---

## Slice 1 — Idempotent migration on load

### Scenario S1.1: Legacy DB-ID-keyed entries are re-keyed to GUID on load
**Priority:** Must
**Closes:** O4 (migration half)

**Gherkin:**
  Given a `maintenance_state.json` with an entry keyed by `"7"` (DB int) whose `collection_id` field is `"abc-guid"`
  And   no entry keyed by `"abc-guid"`
  When  `MaintenanceStateManager` first loads state
  Then  the in-memory dict has the entry keyed by `"abc-guid"` (value preserved)
  And   no entry keyed by `"7"` remains
  And   the canonicalized dict is persisted back to disk

**Verify:** write a fixture JSON with a DB-ID key, construct the manager, call any read method, assert the on-disk file is re-keyed and the state value is byte-identical.

### Scenario S1.2: When both a GUID key and a DB-ID key exist, GUID wins (no data loss)
**Priority:** Must

**Gherkin:**
  Given an entry keyed by `"abc-guid"` (newer, GUID-keyed)
  And   an entry keyed by `"7"` whose `collection_id` is also `"abc-guid"` (legacy)
  When  state loads
  Then  the GUID-keyed entry is kept (it is the canonical one)
  And   the DB-ID-keyed duplicate is dropped
  And   a single entry keyed by `"abc-guid"` remains

**Verify:** fixture with both; assert one entry after load; assert its
fields match the GUID-keyed original.

### Scenario S1.3: Migration is idempotent
**Priority:** Must

**Gherkin:**
  Given a state file already fully canonical (all keys are GUIDs)
  When  state loads and saves N times
  Then  the file content is unchanged after the first load (no churn, no data loss)

**Verify:** load→save→load→save; assert file hash stable from the second save on.

### Scenario S1.4: Migration never raises on malformed entries
**Priority:** Must

**Gherkin:**
  Given an entry whose `collection_id` field is missing or empty
  When  state loads
  Then  that entry is left in place under its original key (not deleted — no data loss)
  And   a warning is logged
  And   no exception escapes

**Verify:** fixture with a malformed entry; assert load returns normally and the entry survives.

### Scenario S1.5: Concurrent load is safe
**Priority:** Should

**Gherkin:**
  Given the manager guarded by `_STATE_LOCK` (existing)
  When  two threads load simultaneously
  Then  the migration runs once and the cache is consistent

**Verify:** two threads calling `list_stale()` on a legacy fixture; assert final on-disk file is canonical.

---

## Slice 2 — Remove the dead dedup guard

### Scenario S2.1: `_deduplicate_states` is deleted after a release window
**Priority:** Should
**Closes:** O4 (dead-code half)

**Gherkin:**
  Given one release has shipped with the Slice 1 migration
  When  Slice 2 lands
  Then  `_deduplicate_states` and its call sites in `mark_collection_stale` / `mark_collection_fresh` are deleted
  And   no test regresses

**Verify:** `grep "_deduplicate_states" kapsula/` returns nothing; full suite green.

### Scenario S2.2: No write path emits a non-GUID key
**Priority:** Must (gate for Slice 2)

**Gherkin:**
  Given the codebase post-Slice-1
  When  audited
  Then  every `states[<key>] = ...` assignment uses `collection.collection_id` (GUID)
  And   `increment_uploads` / `mark_consolidated` key by the `collection_id` argument (GUID)

**Verify:** `grep -n "states\[" kapsula/infrastructure/repositories/processing/maintenance_state_manager.py` — every key expression is the GUID.

---

## Cross-cutting verify
- `pytest tests/test_infrastructure/test_maintenance_state_manager.py -q` → green.
- New migration tests added (`test_canonical_key_migration.py`).
- `ruff check` + `black --check` → clean.
