# Scenarios — Fix Aggregate Index Staleness

---

### Scenario: Maintenance clears staleness on fully-indexed collection
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a collection "health-biosecurity" with 60 completed documents, all chunked and indexed
  And   `list_stale_maintenance` shows `collection_index_stale: true` for this collection
  When  `run_collection_maintenance(collection_id)` completes
  Then  `list_stale_maintenance` no longer shows this collection as stale
  And   the maintenance job result contains non-null FAISS and BM25 paths

**Input table:**
| Field          | Type   | Example                                  |
|----------------|--------|------------------------------------------|
| collection_id  | string | "1fb3eec6-addc-4a92-8801-5110b6162c65"  |

**Expected output:**
| Assertion                         | How to verify                     |
|-----------------------------------|-----------------------------------|
| job.collection_faiss is not None  | `get_maintenance_job(job_id)` shows real path, not `--` |
| job.collection_bm25 is not None   | Same                              |
| stale entry cleared               | `list_stale_maintenance` no longer lists this collection |

**Verify (Classical school, black-box):**
```python
# Arrange: collection exists with indexes on disk, marked stale
stale_before = [s for s in list_stale_maintenance() 
                if s["collection_id"] == "1fb3eec6-addc-4a92-8801-5110b6162c65"]
assert len(stale_before) > 0  # marked stale

# Act
response = run_collection_maintenance("1fb3eec6-addc-4a92-8801-5110b6162c65")
job_id = extract_job_id(response)
poll_until_complete(job_id)
job = get_maintenance_job(job_id)

# Assert
assert job["status"] == "completed"
assert job["collection_faiss"] is not None
assert job["collection_bm25"] is not None

stale_after = [s for s in list_stale_maintenance() 
               if s["collection_id"] == "1fb3eec6-addc-4a92-8801-5110b6162c65"]
assert len(stale_after) == 0  # flag cleared
```

---

### Scenario: Builder returns existing paths when all chunks already indexed
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a collection where all document chunks have already been indexed (hashes in mapping JSON)
  When  `AggregateIndexBuilder.build()` is called
  Then  the existing FAISS and BM25 paths are returned (not None)
  And   no new embeddings are computed

**Verify:**
```python
from kapsula.infrastructure.repositories.indexing.aggregate_index_builder import AggregateIndexBuilder

builder = AggregateIndexBuilder(embedder, DATA_DIR)
faiss_path, bm25_path = builder.build(db, collection_id=col.id, 
                                       account_id=account_guid, 
                                       collection_guid=col.collection_id)

assert faiss_path is not None
assert bm25_path is not None
assert os.path.exists(faiss_path)
assert os.path.exists(bm25_path)
```

---

### Scenario: MaintenanceStateManager uses consistent keys
**Priority:** Should
**Slice:** 1

**Gherkin:**
  Given a collection with state entries under both GUID and DB-ID keys
  When  `mark_collection_fresh(collection, collection_index=True)` is called
  Then  all entries for that collection have `collection_index_stale: false`

**Verify:**
```python
mgr = MaintenanceStateManager()
# After maintenance completes:
states = mgr._load_states()
collection_entries = [
    (key, state) for key, state in states.items()
    if state.get("collection_id") == collection_id
]
for key, state in collection_entries:
    assert state["collection_index_stale"] == False, f"Key {key} still stale"
```

---

### Scenario: Empty collection returns None gracefully
**Priority:** Should
**Slice:** 1

**Gherkin:**
  Given a collection with zero completed documents
  When  `AggregateIndexBuilder.build()` is called
  Then  it returns `(None, None)` and logs an info message

**Verify:**
```python
faiss_path, bm25_path = builder.build(db, collection_id=empty_col.id, ...)
assert faiss_path is None
assert bm25_path is None
# No exception raised
```
