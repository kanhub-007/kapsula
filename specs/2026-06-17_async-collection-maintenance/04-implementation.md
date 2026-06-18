# Implementation Guide — Async Collection Maintenance

---

### Step 1: Create MaintenanceJob dataclass
**File:** `kapsula/presentation/mcp/maintenance_job.py` (new)

Create a simple dataclass to hold maintenance job state. Mirrors `SearchJob` but with maintenance-specific fields.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class MaintenanceJob:
    job_id: str
    collection_id: str
    collection_name: str = "?"
    status: str = "queued"
    stage: str = "queued"
    progress: str = "Maintenance queued"
    summary_updates: int = 0
    summary_failures: int = 0
    collection_faiss: str | None = None
    collection_bm25: str | None = None
    account_faiss: str | None = None
    account_bm25: str | None = None
    cards_created: int = 0
    cards_updated: int = 0
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

**Verify:** Import succeeds, no circular dependencies.

---

### Step 2: Create MaintenanceJobManager
**File:** `kapsula/presentation/mcp/maintenance_job_manager.py` (new)

In-memory manager following the `SearchJobManager` pattern. Stores jobs in a dict with thread-safe access.

```python
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from kapsula.presentation.mcp.maintenance_job import MaintenanceJob


class MaintenanceJobManager:
    def __init__(self, max_jobs: int = 50, ttl_seconds: int = 7200):
        self._jobs: dict[str, MaintenanceJob] = {}
        self._lock = threading.Lock()
        self._max_jobs = max(1, max_jobs)
        self._ttl = timedelta(seconds=max(1, ttl_seconds))

    def create(self, collection_id: str, collection_name: str) -> MaintenanceJob:
        self.cleanup_expired()
        job = MaintenanceJob(
            job_id=str(uuid.uuid4()),
            collection_id=collection_id,
            collection_name=collection_name,
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._enforce_max_jobs_locked()
        return job

    def get(self, job_id: str) -> MaintenanceJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job: MaintenanceJob, **updates: Any) -> None:
        with self._lock:
            for key, value in updates.items():
                setattr(job, key, value)
            job.updated_at = datetime.now(timezone.utc)

    def get_latest_for_collection(self, collection_id: str) -> MaintenanceJob | None:
        with self._lock:
            matching = [
                j for j in self._jobs.values()
                if j.collection_id == collection_id
            ]
            if not matching:
                return None
            return max(matching, key=lambda j: j.created_at)

    def cleanup_expired(self) -> None:
        cutoff = datetime.now(timezone.utc) - self._ttl
        with self._lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job.updated_at < cutoff
                and job.status in {"completed", "failed"}
            ]
            for job_id in expired:
                self._jobs.pop(job_id, None)

    def _enforce_max_jobs_locked(self) -> None:
        if len(self._jobs) <= self._max_jobs:
            return
        removable = sorted(
            self._jobs.values(),
            key=lambda job: job.updated_at,
        )
        for job in removable:
            if len(self._jobs) <= self._max_jobs:
                return
            if job.status in {"completed", "failed"}:
                self._jobs.pop(job.job_id, None)
```

**Verify:** Unit test: create job, get by id, update, get_latest_for_collection, cleanup.

---

### Step 3: Create the maintenance runner function
**File:** `kapsula/presentation/upload/maintenance_runner.py` (new)

Extract the synchronous maintenance logic into a standalone function callable from a background thread. This wraps `CollectionMaintenanceRunner.run()` and updates the `MaintenanceJob` via the manager at each stage.

```python
"""Background maintenance runner — called from a daemon thread."""

from kapsula.infrastructure.data import SessionLocal
from kapsula.infrastructure.logging_config import get_logger
from kapsula.presentation.mcp.maintenance_job import MaintenanceJob
from kapsula.presentation.mcp.maintenance_job_manager import MaintenanceJobManager

logger = get_logger(__name__)

# Singleton manager instance
_maintenance_manager = MaintenanceJobManager()


def get_maintenance_manager() -> MaintenanceJobManager:
    return _maintenance_manager


def run_maintenance_in_background(job_id: str, collection_id: str) -> None:
    """Run collection maintenance in a background thread. Updates job state."""
    manager = get_maintenance_manager()
    job = manager.get(job_id)
    if not job:
        logger.error("Maintenance job not found: %s", job_id)
        return

    db = SessionLocal()
    try:
        from kapsula.infrastructure.data import Collection as OrmCollection
        from kapsula.presentation.upload.collection_maintenance_runner import (
            CollectionMaintenanceRunner,
        )

        col = (
            db.query(OrmCollection)
            .filter(OrmCollection.collection_id == collection_id)
            .first()
        )
        if not col:
            manager.update(job, status="failed", error="Collection not found")
            return

        manager.update(job, status="running", stage="summarizing",
                       progress="Generating collection summary...")
        result = CollectionMaintenanceRunner(db).run(col)

        manager.update(
            job,
            status="completed",
            stage="completed",
            progress="Maintenance complete",
            summary_updates=result.get("summary_updates", 0),
            summary_failures=result.get("summary_failures", 0),
            collection_faiss=result.get("collection_faiss"),
            collection_bm25=result.get("collection_bm25"),
            account_faiss=result.get("account_faiss"),
            account_bm25=result.get("account_bm25"),
            cards_created=result.get("cards_created", 0),
            cards_updated=result.get("cards_updated", 0),
        )
    except Exception as exc:
        logger.error("Maintenance job %s failed: %s", job_id, exc, exc_info=True)
        manager.update(job, status="failed", error=str(exc))
    finally:
        db.close()
```

**Verify:** Start a background thread, poll job, confirm completion.

**Common mistake:** Forgetting to create a new `SessionLocal()` inside the thread — SQLAlchemy sessions are not thread-safe.

---

### Step 4: Modify run_collection_maintenance to be async
**File:** `kapsula/presentation/mcp/tools/collections.py`

Replace the synchronous inline call with job creation + background thread. Keep the existing function signature but change the body.

```python
# Inside register_collection_tools(), replace the existing
# run_collection_maintenance implementation:

@mcp.tool(
    name="run_collection_maintenance",
    description=(
        "Start background collection maintenance: refresh summary, "
        "rebuild FAISS+BM25 indexes, and run consolidation. "
        "Returns a maintenance_job_id immediately — poll progress "
        "with get_maintenance_job(job_id). "
        "This is the all-in-one repair and synthesis tool."
    ),
)
def run_collection_maintenance(collection_id: str) -> str:
    import threading
    db = _get_db()
    try:
        from kapsula.infrastructure.data import Collection as OrmCollection

        col = (
            db.query(OrmCollection)
            .filter(OrmCollection.collection_id == collection_id)
            .first()
        )
        if not col:
            return f"Collection not found: {collection_id}"

        from kapsula.presentation.upload.maintenance_runner import (
            get_maintenance_manager,
            run_maintenance_in_background,
        )

        manager = get_maintenance_manager()
        job = manager.create(collection_id=collection_id, collection_name=col.name)

        threading.Thread(
            target=run_maintenance_in_background,
            args=(job.job_id, collection_id),
            daemon=True,
        ).start()

        return (
            f"Maintenance started for '{col.name}'\n"
            f"  maintenance_job_id: {job.job_id}\n"
            f"  Poll progress: get_maintenance_job(\"{job.job_id}\")"
        )
    finally:
        db.close()
```

**Common mistake:** The `db` session must be closed BEFORE the thread uses its own session. The thread creates its own `SessionLocal()` — never pass a session across threads.

---

### Step 5: Add get_maintenance_job tool
**File:** `kapsula/presentation/mcp/tools/collections.py`

```python
@mcp.tool(
    name="get_maintenance_job",
    description=(
        "Poll a background maintenance job by job_id. "
        "Returns status, stage, progress, and result fields on completion. "
        "Use after run_collection_maintenance() to track progress."
    ),
)
def get_maintenance_job(job_id: str) -> str:
    from kapsula.presentation.upload.maintenance_runner import (
        get_maintenance_manager,
    )

    manager = get_maintenance_manager()
    job = manager.get(job_id)
    if not job:
        return f"Maintenance job not found: {job_id}"

    lines = [
        f"Maintenance Job: {job.job_id}",
        f"  Collection: {job.collection_name} ({job.collection_id})",
        f"  Status: {job.status}",
        f"  Stage: {job.stage}",
        f"  Progress: {job.progress}",
    ]
    if job.status == "completed":
        lines.append(f"  Summary updates: {job.summary_updates}")
        lines.append(f"  Summary failures: {job.summary_failures}")
        lines.append(f"  Collection FAISS: {job.collection_faiss or '--'}")
        lines.append(f"  Collection BM25: {job.collection_bm25 or '--'}")
        lines.append(f"  Account FAISS: {job.account_faiss or '--'}")
        lines.append(f"  Account BM25: {job.account_bm25 or '--'}")
        if job.cards_created or job.cards_updated:
            lines.append(
                f"  Consolidation: {job.cards_created} created, "
                f"{job.cards_updated} updated"
            )
    if job.error:
        lines.append(f"  Error: {job.error}")
    lines.append(f"  Created: {job.created_at.isoformat()}")
    lines.append(f"  Updated: {job.updated_at.isoformat()}")
    return "\n".join(lines)
```

---

### Step 6: (Slice 2) Add get_collection_maintenance_status tool
**File:** `kapsula/presentation/mcp/tools/collections.py`

```python
@mcp.tool(
    name="get_collection_maintenance_status",
    description=(
        "Show the most recent maintenance job for a collection. "
        "Returns last job_id, status, stage, and when it ran."
    ),
)
def get_collection_maintenance_status(collection_id: str) -> str:
    from kapsula.presentation.upload.maintenance_runner import (
        get_maintenance_manager,
    )

    manager = get_maintenance_manager()
    job = manager.get_latest_for_collection(collection_id)
    if not job:
        return f"No maintenance jobs found for collection: {collection_id}"

    lines = [
        f"Latest Maintenance — {job.collection_name}",
        f"  Job ID: {job.job_id}",
        f"  Status: {job.status}",
        f"  Stage: {job.stage}",
        f"  Created: {job.created_at.isoformat()}",
        f"  Updated: {job.updated_at.isoformat()}",
    ]
    if job.error:
        lines.append(f"  Error: {job.error}")
    return "\n".join(lines)
```

---

### Step 7: Register new tools in __init__.py
**File:** `kapsula/presentation/mcp/tools/__init__.py`

Ensure the two new tools are exported. Since `register_collection_tools` registers all tools within it, the new tools added to `collections.py` will automatically be included — no change needed to `__init__.py` unless there's a separate registration step.

**Verify:** Run the MCP server and confirm `get_maintenance_job` and `get_collection_maintenance_status` appear in the tool list.

---

### Step 8: Update server instructions (optional, Slice 2)
**File:** `kapsula/startup/mcp.py`

Update the FastMCP instructions string to document the async maintenance flow.

---

## Verification Checklist

- [ ] `run_collection_maintenance` returns immediately with a job_id
- [ ] `get_maintenance_job(job_id)` shows progress through stages
- [ ] Job completes successfully for a 60-document collection (previously timed out)
- [ ] Job reports failure cleanly if collection not found
- [ ] Invalid job_id returns "not found" message
- [ ] Two concurrent maintenance jobs run independently
- [ ] Server restart loses old jobs gracefully (in-memory pattern)
- [ ] Existing sync path (API tasks.py) still works unchanged
