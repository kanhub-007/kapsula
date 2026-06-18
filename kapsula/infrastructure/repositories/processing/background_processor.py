"""Daemon-thread background processor implementation."""

import threading
from collections.abc import Callable

from sqlalchemy.orm import Session

from kapsula.core.domain.interfaces.background_processor import BackgroundProcessor
from kapsula.infrastructure.data import SessionLocal
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

# Signature of a background document-processing task.
TaskRunner = Callable[[str, str, int, Session, str], None]


class ThreadPoolBackgroundProcessor(BackgroundProcessor):
    """Starts document processing in a daemon thread.

    The concrete task function is injected (composition root) so this
    infrastructure class never imports from presentation — avoiding a layer
    inversion.
    """

    def __init__(
        self,
        task_runner: TaskRunner,
        session_factory: Callable[[], Session] | None = None,
    ):
        self._task_runner = task_runner
        self._session_factory = session_factory or SessionLocal

    def start_processing(
        self,
        job_id: str,
        content: str,
        max_tokens: int,
        ingestion_mode: str,
    ) -> None:
        logger.info(
            "Starting background processing: job_id=%s mode=%s tokens=%s",
            job_id,
            ingestion_mode,
            max_tokens,
        )

        threading.Thread(
            target=self._task_runner,
            args=(job_id, content, max_tokens, self._session_factory(), ingestion_mode),
            daemon=True,
        ).start()
