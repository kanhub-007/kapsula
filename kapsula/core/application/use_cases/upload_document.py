"""Upload document use case — validates, persists, and starts background processing."""

import uuid
from pathlib import Path

from kapsula.core.application.dto.upload_document_result import (
    UploadDocumentResult,
)
from kapsula.core.application.dto.upload_ingestion_mode import (
    UploadIngestionMode,
)
from kapsula.core.domain.entities.document import Document
from kapsula.core.domain.interfaces.background_processor import (
    BackgroundProcessor,
)
from kapsula.core.domain.interfaces.document_repository import (
    DocumentRepository,
)
from kapsula.core.domain.interfaces.progress_tracker import (
    ProgressTracker,
)
import logging

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
        db,
        file_path: str,
        collection_id: str,
        max_tokens: int = 512,
        ingestion_mode: str = "indexed",
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
        job_id = str(uuid.uuid4())

        doc = Document(
            job_id=job_id,
            collection_id=col.id,
            filename=p.name,
            size=len(content.encode("utf-8")),
            ip_address="127.0.0.1",
            content=content,
            status="processing",
        )
        doc = self._document_repository.save_document(db, doc)

        # Register tracking and start background processing
        self._progress_tracker.register_job(
            job_id=job_id,
            filename=p.name,
            collection_name=col.name,
            ingestion_mode=ingestion_mode,
        )
        self._background_processor.start_processing(
            job_id, content, max_tokens, ingestion_mode
        )

        logger.info(
            "Upload started: job_id=%s filename=%s collection=%s mode=%s",
            job_id, p.name, col.name, ingestion_mode,
        )

        return UploadDocumentResult(
            job_id=job_id,
            filename=p.name,
            collection_name=col.name,
            ingestion_mode=ingestion_mode,
        )

    def execute_from_content(
        self,
        db,
        content_bytes: bytes,
        filename: str,
        collection_id: str,
        max_tokens: int = 512,
        ingestion_mode: str = "indexed",
    ) -> UploadDocumentResult:
        """Execute upload from raw content bytes (for HTTP upload routes).

        Writes content to a temp file, delegates to execute(), cleans up.
        """
        import tempfile

        suffix = Path(filename).suffix if Path(filename).suffix else ".md"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="wb") as tmp:
            tmp.write(content_bytes)
            tmp_path = tmp.name
        try:
            result = self.execute(db, tmp_path, collection_id, max_tokens, ingestion_mode)
            return UploadDocumentResult(
                job_id=result.job_id,
                filename=filename,
                collection_name=result.collection_name,
                ingestion_mode=result.ingestion_mode,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
