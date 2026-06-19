"""Upload document use case — validates, persists, and starts background processing."""

import logging
import uuid
from pathlib import Path

from kapsula.core.application.dto.upload_document_result import (
    UploadDocumentResult,
)
from kapsula.core.domain.entities.document import Document
from kapsula.core.domain.entities.upload_ingestion_mode import (
    UploadIngestionMode,
)
from kapsula.core.domain.interfaces.background_processor import (
    BackgroundProcessor,
)
from kapsula.core.domain.interfaces.document_repository import (
    DocumentRepository,
)
from kapsula.core.domain.interfaces.progress_tracker import (
    ProgressTracker,
)
from kapsula.core.domain.interfaces.session import Session

logger = logging.getLogger(__name__)


class UploadDocumentUseCase:
    """Validates a markdown file, persists a Document record, and starts
    background processing."""

    def __init__(
        self,
        background_processor: BackgroundProcessor,
        document_repository: DocumentRepository,
        progress_tracker: ProgressTracker,
    ):
        self._background_processor = background_processor
        self._document_repository = document_repository
        self._progress_tracker = progress_tracker

    def execute(
        self,
        db: Session,
        file_path: str,
        collection_id: str,
        max_tokens: int = 512,
        ingestion_mode: str = "indexed",
        ip_address: str = "127.0.0.1",
    ) -> UploadDocumentResult:
        """Execute the upload workflow.

        Args:
            db: Database session.
            file_path: Path to the .md file on disk.
            collection_id: Target collection GUID.
            max_tokens: Maximum tokens per chunk.
            ingestion_mode: fast | indexed | full.

        Returns:
            UploadDocumentResult.

        Raises:
            ValueError: On validation failure.
        """
        # Normalise and validate ingestion mode
        try:
            ingestion_mode = UploadIngestionMode.normalize(ingestion_mode)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        # Validate file
        p = Path(file_path)
        if not p.exists():
            raise ValueError(f"File not found: {file_path}")
        if p.suffix.lower() != ".md":
            raise ValueError(f"Only .md files accepted, got: {p.suffix}")

        # Validate collection
        col = self._document_repository.find_collection_by_guid(db, collection_id)
        if not col:
            raise ValueError(f"Collection not found: {collection_id}")

        # Read and persist
        content = p.read_text(encoding="utf-8")
        return self._persist_and_dispatch(
            db=db,
            content=content,
            size=len(content.encode("utf-8")),
            filename=p.name,
            collection=col,
            max_tokens=max_tokens,
            ingestion_mode=ingestion_mode,
            ip_address=ip_address,
        )

    def execute_from_content(
        self,
        db: Session,
        content_bytes: bytes,
        filename: str,
        collection_id: str,
        max_tokens: int = 512,
        ingestion_mode: str = "indexed",
        ip_address: str = "127.0.0.1",
    ) -> UploadDocumentResult:
        """Execute upload from raw content bytes (for HTTP upload routes).

        Validates the filename extension directly and persists the decoded
        content without a temp-file round-trip. The caller's filename is
        preserved on the upload record.
        """
        suffix = Path(filename).suffix.lower()
        if suffix != ".md":
            raise ValueError(f"Only .md files accepted, got: {suffix}")

        try:
            ingestion_mode = UploadIngestionMode.normalize(ingestion_mode)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        col = self._document_repository.find_collection_by_guid(db, collection_id)
        if not col:
            raise ValueError(f"Collection not found: {collection_id}")

        content = content_bytes.decode("utf-8")
        return self._persist_and_dispatch(
            db=db,
            content=content,
            size=len(content_bytes),
            filename=filename,
            collection=col,
            max_tokens=max_tokens,
            ingestion_mode=ingestion_mode,
            ip_address=ip_address,
        )

    def _persist_and_dispatch(
        self,
        db: Session,
        content: str,
        size: int,
        filename: str,
        collection,
        max_tokens: int,
        ingestion_mode: str,
        ip_address: str,
    ) -> UploadDocumentResult:
        """Shared body for execute() and execute_from_content() (closes S2).

        Both entry points normalise input to (content, size, filename) and
        delegate here for validation, persistence, progress tracking, and
        background dispatch.
        """
        job_id = str(uuid.uuid4())
        doc = Document(
            job_id=job_id,
            collection_id=collection.id,
            filename=filename,
            size=size,
            ip_address=ip_address,
            content=content,
            status="processing",
        )
        self._document_repository.save_document(db, doc)

        self._progress_tracker.register_job(
            job_id=job_id,
            filename=filename,
            collection_name=collection.name,
            ingestion_mode=ingestion_mode,
        )
        self._background_processor.start_processing(
            job_id, content, max_tokens, ingestion_mode
        )

        logger.info(
            "Upload started: job_id=%s filename=%s collection=%s mode=%s",
            job_id,
            filename,
            collection.name,
            ingestion_mode,
        )
        return UploadDocumentResult(
            job_id=job_id,
            filename=filename,
            collection_name=collection.name,
            ingestion_mode=ingestion_mode,
        )
