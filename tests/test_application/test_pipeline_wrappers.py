"""Tests for pipeline-wired process_document wrappers."""

import logging
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kapsula.infrastructure.data.connection import Base
from kapsula.infrastructure.data.tables.account import Account as OrmAccount
from kapsula.infrastructure.data.tables.collection import Collection as OrmCollection
from kapsula.infrastructure.data.tables.document import Document as OrmDocument


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
    """Create account, collection, and document for processing."""
    account = OrmAccount(
        account_id=str(uuid.uuid4()), name="test-account", ip_address="127.0.0.1"
    )
    db_session.add(account)
    db_session.commit()

    coll = OrmCollection(
        collection_id=str(uuid.uuid4()),
        account_id=account.id,
        name="Test",
        ip_address="127.0.0.1",
    )
    db_session.add(coll)
    db_session.commit()

    doc = OrmDocument(
        job_id="pipeline-test-1",
        collection_id=coll.id,
        filename="test.md",
        size=100,
        content="# Hello\nWorld content here for processing.",
        status="processing",
        ip_address="127.0.0.1",
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    return {"account": account, "collection": coll, "document": doc}


@pytest.fixture
def null_logger():
    logger = logging.getLogger("test_null")
    logger.addHandler(logging.NullHandler())
    return logger


class TestPipelineWrappers:
    """process_document_via_pipeline and process_subdocuments_via_pipeline tests."""

    def test_process_document_via_pipeline_importable(self):
        """The pipeline wrapper must be importable without side effects."""
        from kapsula.presentation.api.tasks import process_document_via_pipeline

        assert callable(process_document_via_pipeline)

    def test_process_subdocuments_via_pipeline_importable(self):
        """The subdocument pipeline wrapper must be importable."""
        from kapsula.presentation.api.tasks import process_subdocuments_via_pipeline

        assert callable(process_subdocuments_via_pipeline)

    def test_pipeline_wrapper_runs_without_crashing(
        self, db_session: Session, seeded_db: dict
    ):
        """process_document_via_pipeline should execute stages without raising."""
        from kapsula.presentation.api.tasks import process_document_via_pipeline

        # This will run the legacy processing through the pipeline adapter
        process_document_via_pipeline(
            job_id="pipeline-test-1",
            markdown_content="# Hello\nWorld content here for processing.",
            max_tokens=512,
            db=db_session,
            ingestion_mode="indexed",
        )

        doc = (
            db_session.query(OrmDocument)
            .filter(OrmDocument.job_id == "pipeline-test-1")
            .first()
        )
        assert doc is not None
        assert doc.status in ("completed", "failed")

    def test_pipeline_wrapper_preserves_progress(
        self, db_session: Session, seeded_db: dict
    ):
        """Pipeline wrapper must populate processing_status dict."""
        from kapsula.presentation.api.tasks import (
            process_document_via_pipeline,
            processing_status,
        )

        process_document_via_pipeline(
            job_id="pipeline-test-1",
            markdown_content="# Hello\nWorld content.",
            max_tokens=512,
            db=db_session,
            ingestion_mode="indexed",
        )

        assert "pipeline-test-1" in processing_status
        entry = processing_status["pipeline-test-1"]
        assert "status" in entry
        assert "progress" in entry
        assert "stage" in entry
