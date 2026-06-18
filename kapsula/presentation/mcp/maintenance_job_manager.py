"""In-memory maintenance job manager — mirrors SearchJobManager pattern."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from kapsula.presentation.mcp.maintenance_job import MaintenanceJob


class MaintenanceJobManager:
    """Owns lifecycle and storage for in-memory maintenance jobs."""

    def __init__(self, max_jobs: int = 50, ttl_seconds: int = 7200):
        self._jobs: dict[str, MaintenanceJob] = {}
        self._lock = threading.Lock()
        self._max_jobs = max(1, max_jobs)
        self._ttl = timedelta(seconds=max(1, ttl_seconds))

    # ── public API ──────────────────────────────────────────

    def create(self, collection_id: str, collection_name: str) -> MaintenanceJob:
        """Create a new job in 'queued' state and return it."""
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
        """Return a job by ID, or None."""
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job: MaintenanceJob, **updates: Any) -> None:
        """Update job fields in-place and refresh timestamp."""
        with self._lock:
            for key, value in updates.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            job.updated_at = datetime.now(UTC)

    def get_latest_for_collection(self, collection_id: str) -> MaintenanceJob | None:
        """Return the most recently created job for a collection."""
        with self._lock:
            matching = [
                j for j in self._jobs.values() if j.collection_id == collection_id
            ]
            if not matching:
                return None
            return max(matching, key=lambda j: j.created_at)

    def cleanup_expired(self) -> None:
        """Remove terminal jobs older than TTL."""
        cutoff = datetime.now(UTC) - self._ttl
        with self._lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job.updated_at < cutoff and job.status in {"completed", "failed"}
            ]
            for job_id in expired:
                self._jobs.pop(job_id, None)

    # ── internal ────────────────────────────────────────────

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
