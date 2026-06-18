"""Daemon-thread background processor implementation."""

import threading

from kapsula.core.domain.interfaces.background_processor import BackgroundProcessor
from kapsula.infrastructure.data import SessionLocal
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class ThreadPoolBackgroundProcessor(BackgroundProcessor):
    """Starts document processing in a daemon thread."""

    def start_processing(
        self,
        job_id: str,
        content: str,
        max_tokens: int,
        ingestion_mode: str,
    ) -> None:
        from kapsula.presentation.api.tasks import (
            process_document_with_subdocuments,
        )

        logger.info(
            "Starting background processing: job_id=%s mode=%s tokens=%s",
            job_id,
            ingestion_mode,
            max_tokens,
        )

        threading.Thread(
            target=process_document_with_subdocuments,
            args=(job_id, content, max_tokens, SessionLocal(), ingestion_mode),
            daemon=True,
        ).start()
