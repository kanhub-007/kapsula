"""Guard against stale in-memory upload progress."""

from typing import Any


class StaleProgressGuard:
    """Resolve terminal database state when live upload progress is stale."""

    ACTIVE_POST_COMPLETION_STAGES = {
        "document_card",
        "collection_summary",
        "collection_aggregate_index",
        "account_aggregate_index",
        "finalizing",
    }

    @classmethod
    def terminal_override(
        cls,
        *,
        document_status: str,
        live_status: str | None,
        live_stage: str | None,
        live_progress: int,
        chunk_count: int,
        duration: float | None,
    ) -> dict[str, Any] | None:
        """Return a terminal progress payload if live progress is stale."""
        if (
            document_status == "completed"
            and live_status != "completed"
            and live_stage not in cls.ACTIVE_POST_COMPLETION_STAGES
            and live_progress <= 80
        ):
            return {
                "status": "completed",
                "progress": 100,
                "stage": "completed",
                "message": (
                    "Document is completed in the database; live progress was "
                    f"stale at {live_progress}%."
                ),
                "chunk_count": chunk_count,
                "duration": duration,
            }

        if document_status == "failed" and live_status != "failed":
            return {
                "status": "failed",
                "progress": 0,
                "stage": "failed",
                "message": "Document failed in the database; live progress was stale.",
                "chunk_count": chunk_count,
                "duration": duration,
            }

        return None
