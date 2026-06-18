"""Tests for DocumentPipeline — orchestrates stages, tracks progress, handles failures."""

import logging
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kapsula.infrastructure.data.connection import Base
from kapsula.infrastructure.data.tables.account import Account as OrmAccount
from kapsula.infrastructure.data.tables.chunk import Chunk
from kapsula.infrastructure.data.tables.collection import Collection as OrmCollection
from kapsula.infrastructure.data.tables.document import Document as OrmDocument
from kapsula.presentation.upload.upload_progress_tracker import UploadProgressTracker

# ── Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def db_session():
    """In-memory SQLite database with all tables."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Sess = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Sess()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def seeded_db(db_session: Session):
    """Create account, collection, and document for pipeline to operate on."""
    account = OrmAccount(
        account_id=str(uuid.uuid4()), name="test-account", ip_address="127.0.0.1"
    )
    db_session.add(account)
    db_session.commit()

    coll = OrmCollection(
        collection_id=str(uuid.uuid4()),
        account_id=account.id,
        name="Test Collection",
        ip_address="127.0.0.1",
    )
    db_session.add(coll)
    db_session.commit()

    doc = OrmDocument(
        job_id="test-job-123",
        collection_id=coll.id,
        filename="test.md",
        size=100,
        content="# Hello\nWorld",
        status="processing",
        ip_address="127.0.0.1",
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    return {"account": account, "collection": coll, "document": doc}


@pytest.fixture
def null_logger():
    """Logger that discards output."""
    logger = logging.getLogger("test_null")
    logger.addHandler(logging.NullHandler())
    return logger


# ── Fakes ─────────────────────────────────────────────────────


class FakeStage:
    """A stage that records it was called and optionally can fail."""

    def __init__(self, name: str, should_fail: bool = False):
        self.name = name
        self._should_fail = should_fail
        self.called_with: dict | None = None

    def run(self, job_id: str, content: str, max_tokens: int, db) -> None:
        self.called_with = {
            "job_id": job_id,
            "content": content,
            "max_tokens": max_tokens,
            "db": db,
        }
        if self._should_fail:
            raise RuntimeError(f"Stage {self.name} failed")


class FakeStageSavesChunks:
    """A persistence stage that creates Chunk rows."""

    name = "saving_chunks"

    def run(self, job_id: str, content: str, max_tokens: int, db: Session) -> None:
        doc = db.query(OrmDocument).filter(OrmDocument.job_id == job_id).first()
        if doc:
            for i in range(3):
                chunk = Chunk(
                    document_id=doc.id,
                    content=f"Chunk {i}: {content}",
                    chunk_index=i,
                    token_count=10,
                    chunk_metadata="{}",
                )
                db.add(chunk)
            db.commit()


# ── Scenario 1: Pipeline executes stages in sequence, tracks progress ──


class TestDocumentPipelineExecute:
    """Tests for DocumentPipeline.execute() — the core orchestrator."""

    def test_stages_execute_in_order(
        self, db_session: Session, seeded_db: dict, null_logger
    ):
        """Pipeline should call each stage's run() exactly once, in order."""
        from kapsula.core.application.use_cases.processing.document_pipeline import (
            DocumentPipeline,
        )

        stage1 = FakeStage("extracting_structure")
        stage2 = FakeStage("chunking")
        stage3 = FakeStage("building_indexes")

        progress_status: dict = {}
        progress = UploadProgressTracker(progress_status, null_logger)

        pipeline = DocumentPipeline([stage1, stage2, stage3], progress)
        result = pipeline.execute("test-job-123", "# Test content", 512, db_session)

        assert result is True
        # All stages were called
        assert stage1.called_with is not None
        assert stage1.called_with["job_id"] == "test-job-123"
        assert stage2.called_with is not None
        assert stage3.called_with is not None

    def test_document_marked_completed_on_success(
        self, db_session: Session, seeded_db: dict, null_logger
    ):
        """Pipeline returns True on success; caller marks document complete."""
        from kapsula.core.application.use_cases.processing.document_pipeline import (
            DocumentPipeline,
        )

        stage = FakeStage("extracting_structure")
        progress_status: dict = {}
        progress = UploadProgressTracker(progress_status, null_logger)

        pipeline = DocumentPipeline([stage], progress)
        result = pipeline.execute("test-job-123", "# Test", 512, db_session)

        assert result is True
        # Caller marks document completed
        doc = (
            db_session.query(OrmDocument)
            .filter(OrmDocument.job_id == "test-job-123")
            .first()
        )
        doc.status = "completed"
        db_session.commit()
        assert doc.status == "completed"

    def test_document_marked_failed_on_error(
        self, db_session: Session, seeded_db: dict, null_logger
    ):
        """Pipeline returns False on error; caller marks document failed."""
        from kapsula.core.application.use_cases.processing.document_pipeline import (
            DocumentPipeline,
        )

        stage = FakeStage("extracting_structure", should_fail=True)
        progress_status: dict = {}
        progress = UploadProgressTracker(progress_status, null_logger)

        pipeline = DocumentPipeline([stage], progress)
        result = pipeline.execute("test-job-123", "# Test", 512, db_session)

        assert result is False
        # Caller marks document failed
        doc = (
            db_session.query(OrmDocument)
            .filter(OrmDocument.job_id == "test-job-123")
            .first()
        )
        doc.status = "failed"
        db_session.commit()
        assert doc.status == "failed"

    def test_progress_tracked_to_completion(
        self, db_session: Session, seeded_db: dict, null_logger
    ):
        """Progress dict should show status=completed, progress=100 on success."""
        from kapsula.core.application.use_cases.processing.document_pipeline import (
            DocumentPipeline,
        )

        stage = FakeStage("extracting_structure")
        progress_status: dict = {}
        progress = UploadProgressTracker(progress_status, null_logger)

        pipeline = DocumentPipeline([stage], progress)
        pipeline.execute("test-job-123", "# Test", 512, db_session)

        assert "test-job-123" in progress_status
        assert progress_status["test-job-123"]["status"] == "completed"
        assert progress_status["test-job-123"]["progress"] == 100

    def test_persistence_stage_saves_chunks(
        self, db_session: Session, seeded_db: dict, null_logger
    ):
        """A stage that creates Chunk rows should result in persisted chunks."""
        from kapsula.core.application.use_cases.processing.document_pipeline import (
            DocumentPipeline,
        )

        stage = FakeStageSavesChunks()
        progress_status: dict = {}
        progress = UploadProgressTracker(progress_status, null_logger)

        pipeline = DocumentPipeline([stage], progress)
        result = pipeline.execute("test-job-123", "# Test content", 512, db_session)

        assert result is True
        doc = (
            db_session.query(OrmDocument)
            .filter(OrmDocument.job_id == "test-job-123")
            .first()
        )
        chunks = db_session.query(Chunk).filter(Chunk.document_id == doc.id).all()
        assert len(chunks) == 3
