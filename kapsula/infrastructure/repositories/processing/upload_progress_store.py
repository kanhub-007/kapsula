"""In-memory live upload-progress store.

A process-local dict that mirrors ``UploadJob`` rows for sub-second progress
polling without hitting the database. Lives in infrastructure because it is
mutable process state shared by background tasks (presentation) and the
progress tracker (infrastructure). Presentation layers import it from here.
"""

from typing import Any

# Process-local live progress: job_id -> progress payload.
processing_status: dict[str, dict[str, Any]] = {}


def get_processing_status(job_id: str) -> dict[str, Any] | None:
    """Return the live progress payload for a job, or None if unknown."""
    return processing_status.get(job_id)
