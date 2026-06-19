"""Tests for UploadDocumentUseCase — validates, persists, and tracks uploads."""

import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kapsula.core.application.dto.upload_document_result import UploadDocumentResult
from kapsula.core.application.use_cases.upload_document import UploadDocumentUseCase
from kapsula.core.domain.entities.collection import Collection as DomainCollection
from kapsula.core.domain.entities.document import Document as DomainDocument
from kapsula.core.domain.interfaces.background_processor import BackgroundProcessor
from kapsula.core.domain.interfaces.document_repository import DocumentRepository
from kapsula.core.domain.interfaces.progress_tracker import ProgressTracker
from kapsula.infrastructure.data.connection import Base
from kapsula.infrastructure.data.tables.account import Account as OrmAccount
from kapsula.infrastructure.data.tables.collection import Collection as OrmCollection

# ── Fakes ──────────────────────────────────────────────────────


class InMemoryDocumentRepository(DocumentRepository):
    """Fake document repository for testing — stores entities in lists."""

    def __init__(self, collection: DomainCollection | None = None):
        self.saved: list[DomainDocument] = []
        self._collection = collection

    def find_document_by_job_id(self, db, job_id: str) -> DomainDocument | None:
        for doc in self.saved:
            if doc.job_id == job_id:
                return doc
        return None

    def find_collection_by_guid(
        self, db, collection_id: str
    ) -> DomainCollection | None:
        return self._collection

    def list_all(self, db) -> list[DomainDocument]:
        return list(self.saved)

    def list_by_collection(self, db, collection_guid: str) -> list[DomainDocument]:
        return [
            d
            for d in self.saved
            if self._collection and d.collection_id == self._collection.id
        ]

    def save_document(self, db, document: DomainDocument) -> DomainDocument:
        doc = DomainDocument(
            id=len(self.saved) + 1,
            job_id=document.job_id,
            collection_id=document.collection_id,
            filename=document.filename,
            size=document.size,
            content=document.content,
            status=document.status,
        )
        self.saved.append(doc)
        return doc

    def cascade_delete_related(self, db, document: DomainDocument) -> int:
        return 0

    def mark_archived(self, db, document: DomainDocument) -> None:
        pass


class FakeBackgroundProcessor(BackgroundProcessor):
    """Records the last job that was submitted for background processing."""

    def __init__(self):
        self.last_job_id: str | None = None
        self.last_content: str | None = None
        self.last_max_tokens: int | None = None
        self.last_ingestion_mode: str | None = None

    def start_processing(
        self, job_id: str, content: str, max_tokens: int, ingestion_mode: str
    ) -> None:
        self.last_job_id = job_id
        self.last_content = content
        self.last_max_tokens = max_tokens
        self.last_ingestion_mode = ingestion_mode


class InMemoryProgressTracker(ProgressTracker):
    """Records registered jobs."""

    def __init__(self):
        self.jobs: dict[str, dict] = {}

    def register_job(
        self, job_id: str, filename: str, collection_name: str, ingestion_mode: str
    ) -> None:
        self.jobs[job_id] = {
            "filename": filename,
            "collection_name": collection_name,
            "ingestion_mode": ingestion_mode,
        }

    def set_queued(self, job_id: str, ingestion_mode: str) -> None:
        pass


class RecordingMaintenanceState:
    """Fake MaintenanceStateTracker — records increment_uploads calls."""

    def __init__(self):
        self.calls: list[str] = []

    def increment_uploads(self, collection_id: str) -> None:
        self.calls.append(collection_id)


# ── Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def db_session():
    """In-memory SQLite database with tables for ORM-backed collection lookup."""
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
def domain_collection(db_session: Session) -> DomainCollection:
    """Create a real collection in the in-memory DB (needed for ORM-backed repo tests)."""
    account = OrmAccount(
        account_id=str(uuid.uuid4()), name="test-account", ip_address="127.0.0.1"
    )
    db_session.add(account)
    db_session.commit()
    coll = OrmCollection(
        collection_id="coll-test-123",
        account_id=account.id,
        name="Test Collection",
        ip_address="127.0.0.1",
    )
    db_session.add(coll)
    db_session.commit()
    db_session.refresh(coll)
    return DomainCollection(
        id=coll.id,
        collection_id=coll.collection_id,
        account_id=coll.account_id,
        name=coll.name,
        created_at=coll.created_at,
        ip_address=coll.ip_address,
    )


# ── Scenario 1: Happy path — valid .md file upload succeeds ────


class TestUploadDocumentUseCase:
    """Tests for UploadDocumentUseCase.execute() and execute_from_content()."""

    def test_execute_with_valid_md_file_succeeds(
        self, domain_collection: DomainCollection
    ):
        """Happy path: valid .md file, existing collection → returns UploadDocumentResult."""
        repo = InMemoryDocumentRepository(collection=domain_collection)
        progress = InMemoryProgressTracker()
        processor = FakeBackgroundProcessor()
        use_case = UploadDocumentUseCase(
            processor, repo, progress, RecordingMaintenanceState()
        )

        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# Test Document\nContent goes here.")
            f.flush()
            tmp_path = f.name

        try:
            result = use_case.execute(
                db=None,
                file_path=tmp_path,
                collection_id="coll-test-123",
                ingestion_mode="indexed",
            )

            assert isinstance(result, UploadDocumentResult)
            assert result.job_id is not None
            assert result.filename == Path(tmp_path).name
            assert result.collection_name == "Test Collection"
            assert result.ingestion_mode == "indexed"

            # Document was saved via repository
            assert len(repo.saved) == 1
            assert repo.saved[0].status == "processing"

            # Background processor was invoked
            assert processor.last_job_id == result.job_id
            assert processor.last_ingestion_mode == "indexed"

            # Progress tracker recorded the job
            assert result.job_id in progress.jobs
            assert progress.jobs[result.job_id]["filename"] == Path(tmp_path).name
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_execute_rejects_non_md_file(self, domain_collection: DomainCollection):
        """Non-.md file should raise ValueError."""
        repo = InMemoryDocumentRepository(collection=domain_collection)
        progress = InMemoryProgressTracker()
        processor = FakeBackgroundProcessor()
        use_case = UploadDocumentUseCase(
            processor, repo, progress, RecordingMaintenanceState()
        )

        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("not markdown")
            f.flush()
            tmp_path = f.name

        try:
            with pytest.raises(ValueError, match="Only .md files accepted"):
                use_case.execute(
                    db=None, file_path=tmp_path, collection_id="coll-test-123"
                )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_execute_rejects_missing_collection(
        self, domain_collection: DomainCollection
    ):
        """Missing collection should raise ValueError."""
        # Repository returns None for unknown collection
        repo = InMemoryDocumentRepository(collection=None)
        progress = InMemoryProgressTracker()
        processor = FakeBackgroundProcessor()
        use_case = UploadDocumentUseCase(
            processor, repo, progress, RecordingMaintenanceState()
        )

        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# Test")
            f.flush()
            tmp_path = f.name

        try:
            with pytest.raises(ValueError, match="Collection not found"):
                use_case.execute(
                    db=None, file_path=tmp_path, collection_id="nonexistent"
                )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_execute_with_invalid_ingestion_mode(
        self, domain_collection: DomainCollection
    ):
        """Invalid ingestion_mode should raise ValueError."""
        repo = InMemoryDocumentRepository(collection=domain_collection)
        progress = InMemoryProgressTracker()
        processor = FakeBackgroundProcessor()
        use_case = UploadDocumentUseCase(
            processor, repo, progress, RecordingMaintenanceState()
        )

        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# Test")
            f.flush()
            tmp_path = f.name

        try:
            with pytest.raises(ValueError):
                use_case.execute(
                    db=None,
                    file_path=tmp_path,
                    collection_id="coll-test-123",
                    ingestion_mode="invalid",
                )
        finally:
            Path(tmp_path).unlink(missing_ok=True)


# ── Scenario 3: execute_from_content writes temp file, cleans up ─


class TestExecuteFromContent:
    """Tests for execute_from_content() — bytes path (no temp file)."""

    def test_persists_decoded_content_and_dispatches(
        self, domain_collection: DomainCollection
    ):
        """execute_from_content decodes bytes and dispatches to background processing."""
        repo = InMemoryDocumentRepository(collection=domain_collection)
        progress = InMemoryProgressTracker()
        processor = FakeBackgroundProcessor()
        use_case = UploadDocumentUseCase(
            processor, repo, progress, RecordingMaintenanceState()
        )

        content_bytes = "# Hello from bytes\nUnicode: café ☕".encode()
        result = use_case.execute_from_content(
            db=None,
            content_bytes=content_bytes,
            filename="test.md",
            collection_id="coll-test-123",
            ingestion_mode="indexed",
        )

        assert result.job_id is not None
        assert result.filename == "test.md"
        assert result.ingestion_mode == "indexed"
        assert len(repo.saved) == 1
        # Content is decoded UTF-8, not a temp-file path.
        assert repo.saved[0].content == "# Hello from bytes\nUnicode: café ☕"
        assert repo.saved[0].filename == "test.md"
        assert repo.saved[0].size == len(content_bytes)
        assert processor.last_job_id == result.job_id
        assert processor.last_content == repo.saved[0].content

    def test_execute_from_content_rejects_bad_extension(
        self, domain_collection: DomainCollection
    ):
        """Non-.md filename should raise ValueError."""
        repo = InMemoryDocumentRepository(collection=domain_collection)
        progress = InMemoryProgressTracker()
        processor = FakeBackgroundProcessor()
        use_case = UploadDocumentUseCase(
            processor, repo, progress, RecordingMaintenanceState()
        )

        with pytest.raises(ValueError, match="Only .md files accepted"):
            use_case.execute_from_content(
                db=None,
                content_bytes=b"test",
                filename="bad.txt",
                collection_id="coll-test-123",
            )

    # ── H1: consolidation side-effect lives in the use case, not the route ──

    def test_upload_marks_consolidation_stale(
        self, domain_collection: DomainCollection
    ):
        """Upload must flag the collection stale so deferred maintenance runs.

        Previously this side-effect lived only in the MCP tool wrapper, so the
        REST API path silently skipped it (H1). Now the use case owns it, so
        every caller (MCP, API, future ones) gets it for free.
        """
        repo = InMemoryDocumentRepository(collection=domain_collection)
        progress = InMemoryProgressTracker()
        processor = FakeBackgroundProcessor()
        maintenance = RecordingMaintenanceState()
        use_case = UploadDocumentUseCase(processor, repo, progress, maintenance)

        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write("# Test\nContent.")
            f.flush()
            tmp_path = f.name

        try:
            use_case.execute(
                db=None,
                file_path=tmp_path,
                collection_id="coll-test-123",
                ingestion_mode="indexed",
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        assert maintenance.calls == ["coll-test-123"]
