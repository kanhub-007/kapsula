"""Background maintenance runner — called from a daemon thread.

Extracted from the synchronous MCP tool so maintenance can run
asynchronously without blocking the tool call.
"""

import threading

from kapsula.infrastructure.data import SessionLocal
from kapsula.infrastructure.logging_config import get_logger
from kapsula.presentation.mcp.maintenance_job_manager import MaintenanceJobManager

logger = get_logger(__name__)

# Singleton — shared between the tool (creates jobs) and the runner (updates them).
_manager = MaintenanceJobManager()

# Serializes maintenance runs across collections. SQLite serializes writers
# anyway, and the consolidation/summary steps hold transactions open across
# long LLM calls — parallel maintenance causes `database is locked` even with
# busy_timeout (5s is nothing vs a 60s LLM call). See spec
# 2026-06-17_serialize-maintenance-jobs for the full rationale.
_maintenance_lock = threading.Lock()


def get_maintenance_manager() -> MaintenanceJobManager:
    """Return the singleton MaintenanceJobManager."""
    return _manager


def run_maintenance_in_background(job_id: str, collection_id: str) -> None:
    """Run full collection maintenance in a background daemon thread.

    Maintenance runs are serialized via ``_maintenance_lock`` so only one
    job holds a write transaction at a time. While waiting for a prior job
    to finish, this job reports ``status="queued"`` so clients can see it
    is waiting. Updates the MaintenanceJob via the singleton manager at
    each stage so the client can poll progress with get_maintenance_job().
    """
    manager = get_maintenance_manager()
    job = manager.get(job_id)
    if not job:
        logger.error("Maintenance job not found in manager: %s", job_id)
        return

    # Wait for any in-flight maintenance to finish. SQLite writers are
    # serialized; running two consolidations in parallel holds transactions
    # open across long LLM calls and triggers `database is locked`.
    if not _maintenance_lock.acquire(blocking=False):
        manager.update(
            job,
            status="queued",
            stage="queued",
            progress="Waiting for another maintenance job to finish...",
        )
        logger.info(
            "Maintenance job %s queued (another maintenance is running)", job_id
        )
        _maintenance_lock.acquire()

    try:
        _run_maintenance_locked(job, job_id, collection_id, manager)
    finally:
        _maintenance_lock.release()


def _run_maintenance_locked(
    job, job_id: str, collection_id: str, manager: MaintenanceJobManager
) -> None:
    """Execute maintenance. Caller holds ``_maintenance_lock``."""
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
            manager.update(
                job,
                status="failed",
                stage="failed",
                error=f"Collection not found: {collection_id}",
            )
            return

        manager.update(
            job,
            status="running",
            stage="starting",
            progress="Starting collection maintenance...",
        )

        def _on_progress(stage: str, progress: str, detail: str) -> None:
            manager.update(
                job,
                stage=stage,
                progress=f"{progress}" + (f" ({detail})" if detail else ""),
            )

        result = CollectionMaintenanceRunner(db).run(
            col, progress_callback=_on_progress
        )

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
            cards_enriched=result.get("cards_enriched", 0),
        )

        logger.info(
            "Maintenance job %s completed: %d summaries, %d cards",
            job_id,
            result.get("summary_updates", 0),
            result.get("cards_created", 0),
        )

    except Exception as exc:
        logger.exception("Maintenance job %s failed: %s", job_id, exc)
        manager.update(
            job,
            status="failed",
            stage="failed",
            error=str(exc),
        )
    finally:
        db.close()
