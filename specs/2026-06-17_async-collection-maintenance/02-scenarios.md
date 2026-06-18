# Scenarios — Async Collection Maintenance

---

### Scenario: Start maintenance on a collection and poll until complete
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a collection "escapekey" with 60 completed documents and stale indexes
  When  the user calls run_collection_maintenance(collection_id)
  Then  the call returns immediately with a maintenance_job_id
  And   the job status is "queued" or "running"
  And   calling get_maintenance_job(job_id) returns the current stage and progress
  And   after completion, status is "completed" and result includes summary_updates, index paths

**Input table:**
| Field          | Type   | Example                                  | Constraints       |
|----------------|--------|------------------------------------------|-------------------|
| collection_id  | string | "c4b57794-4631-43e6-b3b5-23a7d1608f5f"  | Required, valid GUID |

**Expected output (immediate return):**
| Assertion                         | How to verify                     |
|-----------------------------------|-----------------------------------|
| response contains "maintenance_job_id" | String contains a UUID           |
| response contains "Poll:"         | Instructions for polling          |

**Expected output (after polling get_maintenance_job):**
| Assertion                         | How to verify                     |
|-----------------------------------|-----------------------------------|
| job.status is "completed"         | Inspect returned job dict         |
| job.summary_updates > 0           | Inspect result field              |
| job.collection_faiss is not None  | Inspect result field              |
| No error present                  | job.error is None                 |

**Verify (Classical school, black-box):**
```python
# Arrange
db = SessionLocal()
col = db.query(OrmCollection).filter(...).first()
# Ensure collection has completed documents and stale state

# Act
response = run_collection_maintenance(collection_id=col.collection_id)

# Assert — immediate return
assert "maintenance_job_id" in response
job_id = extract_job_id(response)

# Poll until complete
import time
for _ in range(60):  # up to 10 minutes
    job = get_maintenance_job(job_id)
    if job["status"] in ("completed", "failed"):
        break
    time.sleep(10)

assert job["status"] == "completed"
assert job["summary_updates"] > 0
assert job["error"] is None
```

**Also test:**
- Collection not found → error message, no job created
- Collection with zero documents → job completes with summary_updates=0
- Two maintenance jobs for the same collection → both run independently (no dedup in Slice 1)

---

### Scenario: Maintenance job reports progress through distinct stages
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a maintenance job is running on a collection with 60 documents
  When  the user polls get_maintenance_job(job_id) at different times
  Then  the stage field transitions through: "summarizing" → "indexing" → "consolidating" → "completed"

**Input table:**
| Field   | Type   | Example                                  | Constraints       |
|---------|--------|------------------------------------------|-------------------|
| job_id  | string | "a1b2c3d4-..."                           | Required, valid GUID |

**Expected output:**
| Assertion                         | How to verify                     |
|-----------------------------------|-----------------------------------|
| Stage starts as "queued" or "summarizing" | Check stage field          |
| Stage progresses through known values | stage in {"queued", "summarizing", "indexing", "consolidating", "completed", "failed"} |
| Completed job has final stage     | stage == "completed"              |

**Verify:**
```python
job = get_maintenance_job(job_id)
assert job["stage"] in {"queued", "summarizing", "indexing", "consolidating", "completed", "failed"}

# After waiting for completion
assert job["status"] == "completed"
assert job["stage"] == "completed"
```

**Also test:**
- Failed job reports the failing stage (e.g., stage="consolidating", status="failed", error="...")

---

### Scenario: Maintenance job survives MCP client disconnection
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given a maintenance job has been started via run_collection_maintenance
  When  the MCP client disconnects (or the polling loop stops)
  Then  the background daemon thread continues processing
  And   when the client reconnects and calls get_maintenance_job(job_id), the job has progressed or completed

**Verify:**
```python
# Start the job
response = run_collection_maintenance(collection_id=col_id)
job_id = extract_job_id(response)

# Simulate disconnection (do nothing for 5 minutes)
import time; time.sleep(300)

# Reconnect and poll
job = get_maintenance_job(job_id)
assert job["status"] in ("running", "completed")  # progressed, not stuck
```

---

### Scenario: get_maintenance_job returns clear error for invalid job_id
**Priority:** Should
**Slice:** 1

**Gherkin:**
  Given a non-existent maintenance_job_id
  When  the user calls get_maintenance_job("nonexistent-id")
  Then  an error message is returned indicating the job was not found

**Input table:**
| Field   | Type   | Example         | Constraints       |
|---------|--------|-----------------|-------------------|
| job_id  | string | "nonexistent-id"| Any string        |

**Output:**
| Assertion                         | How to verify                     |
|-----------------------------------|-----------------------------------|
| Response contains "not found"     | String match                      |

---

### Scenario: get_collection_maintenance_status shows latest job for a collection
**Priority:** Should
**Slice:** 2

**Gherkin:**
  Given a collection that has had maintenance jobs run
  When  the user calls get_collection_maintenance_status(collection_id)
  Then  the response shows the most recent job's status, stage, and when it ran

**Verify:**
```python
status = get_collection_maintenance_status(collection_id=col_id)
assert "last_job_id" in status
assert "last_status" in status
assert "last_run_at" in status
```
