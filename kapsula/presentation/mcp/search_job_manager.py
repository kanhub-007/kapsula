"""In-memory MCP background search job manager."""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from kapsula.presentation.mcp.search_job import SearchJob


class SearchJobManager:
    """Owns lifecycle and storage for in-memory MCP background jobs."""

    def __init__(self, max_jobs: int = 100, ttl_seconds: int = 3600):
        self._jobs: dict[str, SearchJob] = {}
        self._lock = threading.Lock()
        self._max_jobs = max(1, max_jobs)
        self._ttl = timedelta(seconds=max(1, ttl_seconds))

    def start(
        self,
        params: dict[str, Any],
        runner: Callable[[SearchJob], Awaitable[None]],
    ) -> SearchJob:
        """Create and start a background job using the active event loop."""
        self.cleanup_expired()
        job = SearchJob(job_id=str(uuid.uuid4()), params=params)
        task = asyncio.create_task(runner(job))
        job.task = task
        with self._lock:
            self._jobs[job.job_id] = job
            self._enforce_max_jobs_locked()
        return job

    def get(self, job_id: str) -> SearchJob | None:
        """Return a job by ID."""
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job: SearchJob, **updates: Any) -> None:
        """Update a job in-place and refresh its timestamp."""
        with self._lock:
            for key, value in updates.items():
                setattr(job, key, value)
            job.updated_at = datetime.now(timezone.utc)

    def cancel(self, job_id: str) -> SearchJob | None:
        """Cancel a queued or running job."""
        job = self.get(job_id)
        if not job:
            return None
        if job.status not in {"completed", "failed", "cancelled"}:
            if job.task:
                job.task.cancel()
            self.update(job, status="cancelled", progress="Cancellation requested")
        return job

    def clear(self) -> None:
        """Cancel and remove all jobs. Intended for tests/cache resets."""
        with self._lock:
            jobs = list(self._jobs.values())
            self._jobs.clear()
        for job in jobs:
            if job.task and not job.task.done():
                job.task.cancel()

    def cleanup_expired(self) -> None:
        """Remove expired terminal jobs."""
        cutoff = datetime.now(timezone.utc) - self._ttl
        with self._lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job.updated_at < cutoff
                and job.status in {"completed", "failed", "cancelled"}
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
            if job.status in {"completed", "failed", "cancelled"}:
                self._jobs.pop(job.job_id, None)
