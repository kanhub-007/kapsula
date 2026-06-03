"""Interface for tracking background processing progress."""

from abc import ABC, abstractmethod


class ProgressTracker(ABC):
    """Tracks the lifecycle of a background processing job.

    Abstracts the module-level ``processing_status`` dict in tasks.py
    so use cases don't depend on presentation-layer singletons."""

    @abstractmethod
    def register_job(
        self,
        job_id: str,
        filename: str,
        collection_name: str,
        ingestion_mode: str,
    ) -> None:
        """Record that a new job has been queued."""

    @abstractmethod
    def set_queued(self, job_id: str, ingestion_mode: str) -> None:
        """Mark a job as queued for processing."""
