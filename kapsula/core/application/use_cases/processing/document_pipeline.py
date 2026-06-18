"""Orchestrates document processing stages in sequence.

The pipeline is a pure orchestrator — it runs stages in order and tracks
progress. It does NOT touch ORM models directly. Callers wrap it with
DB session management and document status updates.
"""

import logging
import time

logger = logging.getLogger(__name__)


class DocumentPipeline:
    """Orchestrates document processing stages in sequence.

    Each stage is a :class:`PipelineStage` that receives the job's markdown
    content, processes it (e.g., chunking, embedding, persistence), and
    optionally updates the database.

    Progress is reported through a ``UploadProgressTracker`` instance
    passed at construction time.
    """

    def __init__(self, stages: list, progress):
        self._stages = stages
        self._progress = progress

    def execute(self, job_id: str, content: str, max_tokens: int, db) -> bool:
        """Run all stages in sequence for a single document.

        Args:
            job_id: The upload job GUID.
            content: Raw markdown content to process.
            max_tokens: Maximum tokens per chunk.
            db: Database session (the pipeline does not close it).

        Returns:
            True if all stages succeeded, False if any stage raised.
        """
        start_time = time.time()
        try:
            for stage in self._stages:
                self._progress.set(
                    job_id,
                    status="processing",
                    progress=0,
                    stage=stage.name,
                    message=f"Running {stage.name}...",
                )
                stage.run(job_id, content, max_tokens, db)

            self._progress.set(
                job_id,
                status="completed",
                progress=100,
                stage="completed",
                message=f"Processing completed successfully in {time.time() - start_time:.2f}s.",
            )
            return True
        except Exception as e:
            logger.exception("Pipeline failed for %s: %s", job_id, e)
            self._progress.set(
                job_id,
                status="failed",
                progress=0,
                stage="failed",
                message=f"Processing failed: {e}",
            )
            return False
