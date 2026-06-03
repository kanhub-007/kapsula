"""Daemon-thread background processor implementation."""

import threading

from doc_search.core.domain.interfaces.background_processor import BackgroundProcessor
from doc_search.infrastructure.data import SessionLocal
from doc_search.infrastructure.logging_config import get_logger

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
        from doc_search.presentation.api.tasks import (
            process_document_with_subdocuments,
        )

        logger.info(
            "Starting background processing: job_id=%s mode=%s tokens=%s",
            job_id, ingestion_mode, max_tokens,
        )

        threading.Thread(
            target=process_document_with_subdocuments,
            args=(job_id, content, max_tokens, SessionLocal(), ingestion_mode),
            daemon=True,
        ).start()
