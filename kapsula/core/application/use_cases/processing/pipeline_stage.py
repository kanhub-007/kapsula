"""Protocol for a single stage in the document processing pipeline."""

from typing import Any, Protocol


class PipelineStage(Protocol):
    """A single stage in the document processing pipeline.

    Implementations must provide a ``name`` attribute (used for progress
    tracking) and a ``run()`` method that executes the stage logic.
    """

    name: str

    def run(self, job_id: str, content: str, max_tokens: int, db: Any) -> None:
        """Execute this stage.

        Args:
            job_id: The upload job GUID.
            content: The markdown content being processed.
            max_tokens: Maximum tokens per chunk.
            db: Database session.

        Raises:
            Any exception on failure. The pipeline catches and marks the
            document as failed.
        """
        ...
