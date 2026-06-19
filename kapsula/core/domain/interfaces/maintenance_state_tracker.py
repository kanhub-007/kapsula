"""Interface for deferred-maintenance state tracking.

Implemented by infrastructure (MaintenanceStateManager) and consumed by the
upload/delete use cases so they can mark consolidation stale as an
unavoidable side-effect of changing a collection's contents (closes H1).
"""

from typing import Protocol


class MaintenanceStateTracker(Protocol):
    """Tracks when a collection's derived artifacts need rebuilding."""

    def increment_uploads(self, collection_id: str) -> None:
        """Note that a collection's contents changed (upload or delete).

        Implementations must be idempotent against a missing prior state.
        Failures here are best-effort: callers wrap this in a try/except so
        state-tracking never aborts the primary operation.
        """
        ...
