"""Upload progress tracking and stage instrumentation."""

import time
from typing import Any, MutableMapping


class UploadProgressTracker:
    """Tracks live upload progress and emits per-stage timing logs."""

    def __init__(self, status_store: MutableMapping[str, dict[str, Any]], logger: Any):
        self._status_store = status_store
        self._logger = logger

    def set(
        self,
        job_id: str,
        *,
        status: str,
        progress: int,
        stage: str,
        message: str,
        **extra: Any,
    ) -> None:
        """Update live upload progress with a consistent payload shape."""
        payload: dict[str, Any] = {
            "status": status,
            "progress": progress,
            "stage": stage,
            "message": message,
            "updated_at": time.time(),
        }
        payload.update(extra)
        self._status_store[job_id] = payload

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Return current live progress for a job."""
        return self._status_store.get(job_id)

    def log_stage(
        self,
        job_id: str,
        stage: str,
        stage_start_time: float,
        **metrics: Any,
    ) -> None:
        """Emit a structured timing log for an upload stage."""
        elapsed = time.time() - stage_start_time
        metric_suffix = ""
        if metrics:
            metric_suffix = " " + " ".join(
                f"{key}={value}" for key, value in metrics.items() if value is not None
            )
        self._logger.info(
            "upload.stage job_id=%s stage=%s elapsed=%.2fs%s",
            job_id,
            stage,
            elapsed,
            metric_suffix,
        )

    @staticmethod
    def elapsed_message(start_time: float) -> str:
        """Return a human-readable elapsed-time fragment."""
        return f"elapsed {time.time() - start_time:.1f}s"
