"""Repository interface for persistent upload-job records."""

from abc import ABC, abstractmethod
from typing import Any


class UploadJobRepository(ABC):
    """Persists UploadJob rows for progress history and metrics.

    Implementations live in infrastructure (SQLAlchemy). The progress-sync
    side effect (writing to the live in-memory tracker) is intentionally NOT
    part of this interface — callers compose that separately.
    """

    @abstractmethod
    def create(
        self,
        job_id: str,
        *,
        filename: str,
        collection_id: int | None,
        collection_name: str,
        ingestion_mode: str,
    ) -> None:
        """Insert a new upload-job row in 'processing' state."""

    @abstractmethod
    def update(self, job_id: str, **fields: Any) -> None:
        """Patch zero or more columns on an existing upload-job row."""

    @abstractmethod
    def get(self, job_id: str) -> dict[str, Any] | None:
        """Return one job as a plain dict, or None if not found."""

    @abstractmethod
    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent upload jobs ordered by creation time (newest first)."""
