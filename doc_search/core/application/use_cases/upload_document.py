"""Upload document use case — validates, persists, and starts background processing."""

import uuid
import threading
from pathlib import Path
from dataclasses import dataclass

from sqlalchemy.orm import Session

from doc_search.core.application.dto.upload_ingestion_mode import (
    UploadIngestionMode,
)
from doc_search.infrastructure.data import (
    SessionLocal,
    Document,
    Collection,
)
from doc_search.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class UploadDocumentResult:
    """Result of an upload request."""

    job_id: str
    filename: str
    collection_name: str
    ingestion_mode: str
    status: str = "processing"
    error: str | None = None


class UploadDocumentUseCase:
    """Validates a markdown file, persists a Document record, and starts
    background processing via ``process_document_with_subdocuments``."""

    def execute(
        self,
        db: Session,
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
            ValueError: On validation failure (file not found, bad extension,
                        collection missing, invalid ingestion mode).
        """
        try:
            ingestion_mode = UploadIngestionMode.normalize(ingestion_mode)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        p = Path(file_path)
        if not p.exists():
            raise ValueError(f"File not found: {file_path}")
        if p.suffix.lower() != ".md":
            raise ValueError(f"Only .md files accepted, got: {p.suffix}")

        col = (
            db.query(Collection)
            .filter(Collection.collection_id == collection_id)
            .first()
        )
        if not col:
            raise ValueError(f"Collection not found: {collection_id}")

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
        db.add(doc)
        db.commit()
        db.refresh(doc)

        # Start background processing in a daemon thread
        from doc_search.presentation.api.tasks import (
            process_document_with_subdocuments,
            processing_status,
        )
        from doc_search.presentation.upload.upload_job_manager import (
            UploadJobManager,
        )

        processing_status[job_id] = {
            "status": "processing",
            "progress": 0,
            "stage": "queued",
            "message": f"Document queued for {ingestion_mode} ingestion...",
            "ingestion_mode": ingestion_mode,
        }
        UploadJobManager().create(
            job_id,
            filename=p.name,
            collection_id=col.id,
            collection_name=col.name,
            ingestion_mode=ingestion_mode,
        )

        threading.Thread(
            target=process_document_with_subdocuments,
            args=(job_id, content, max_tokens, SessionLocal(), ingestion_mode),
            daemon=True,
        ).start()

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
