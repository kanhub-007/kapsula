# Maintenance-State Canonical-Key Migration

## User Story
As a maintainer of kapsula, I want the maintenance-state JSON file keyed
canonically by collection GUID (with the legacy DB-integer-ID entries
migrated away), so that the defensive `_deduplicate_states` repair-on-
read code can be deleted and the on-disk format has a single,
documented key.

## Context

`MaintenanceStateManager` persists deferred-maintenance flags to
`data/maintenance_state.json` as `{key: state}`. A historical bug:
`increment_uploads` created entries **keyed by GUID** while
`mark_collection_stale`/`mark_collection_fresh` used the **DB integer
ID** as the key. The result was two entries for the same collection,
which `_deduplicate_states` cleans up at read time (it scans for any
entry whose key ≠ its `collection_id` field and deletes it).

After the A3 fix, **all current write paths key by GUID**
(`key = collection.collection_id`). The dedup method is now purely a
legacy-data repair. But deleting it blindly would leave any deployment
with an old `maintenance_state.json` carrying orphaned DB-ID-keyed
entries that nothing reads (silent staleness for those collections
until the next `mark_collection_stale` re-creates a GUID entry).

This is a small but **data-integrity-sensitive** change: a botched
migration silently loses maintenance state. The non-obvious part is the
migration sequence — it must be idempotent, must not lose state, and
must handle the window where an old process might still be running.

## Pattern decision
Not a GoF pattern — a **one-shot idempotent data migration** run at
load time. The principle in play is *make unsafe state impossible*:
after migration, the in-memory dict is keyed only by GUID, and
`_deduplicate_states` becomes provably dead code.

## Non-Goals
- Moving maintenance state into SQLite (tracked separately; the JSON
  store stays).
- Changing the state field names or the `_new_state` shape.
- Touching the in-memory cache added by the PE1 fix.

## Slices
- **Slice 1** — Add an idempotent `_canonicalize_keys` migration in
  `_load_states`; keep `_deduplicate_states` as a belt-and-braces
  guard during the transition.
- **Slice 2** — After a release window, delete `_deduplicate_states`
  and its two call sites.
