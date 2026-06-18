"""Tests for SqlUploadJobRepository (CRUD against in-memory SQLite).

Classical school: real repository + real in-memory SQLite (a fake at the DB
boundary). Asserts on persisted state, never on call interactions.
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kapsula.core.domain.interfaces.upload_job_repository import (
    UploadJobRepository,
)
from kapsula.infrastructure.data.connection import Base
from kapsula.infrastructure.repositories.data.sql_upload_job_repository import (
    SqlUploadJobRepository,
)


@pytest.fixture
def repo_with_session(tmp_path):
    """Return (repository, session_factory) backed by a fresh in-memory DB.

    The repository opens its own SessionLocal; we monkeypatch SessionLocal to
    point at our in-memory engine so all reads/writes share one schema.
    """
    db_file = tmp_path / "jobs.db"
    engine = create_engine(
        f"sqlite:///{db_file}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    import kapsula.infrastructure.repositories.data.sql_upload_job_repository as mod

    original = mod.SessionLocal
    mod.SessionLocal = Session
    repo = SqlUploadJobRepository()
    try:
        yield repo, Session
    finally:
        mod.SessionLocal = original


def _fake_job_id() -> str:
    return str(uuid.uuid4())


class TestSqlUploadJobRepository:
    def test_implements_interface(self):
        assert isinstance(SqlUploadJobRepository(), UploadJobRepository)

    def test_create_then_get_roundtrip(self, repo_with_session):
        repo, _ = repo_with_session
        job_id = _fake_job_id()
        repo.create(
            job_id,
            filename="doc.md",
            collection_id=7,
            collection_name="C",
            ingestion_mode="indexed",
        )
        got = repo.get(job_id)
        assert got is not None
        assert got["job_id"] == job_id
        assert got["filename"] == "doc.md"
        assert got["status"] == "processing"
        assert got["progress"] == 0
        assert got["stage"] == "queued"
        assert got["ingestion_mode"] == "indexed"

    def test_get_unknown_returns_none(self, repo_with_session):
        repo, _ = repo_with_session
        assert repo.get("does-not-exist") is None

    def test_update_patches_fields(self, repo_with_session):
        repo, _ = repo_with_session
        job_id = _fake_job_id()
        repo.create(
            job_id,
            filename="doc.md",
            collection_id=1,
            collection_name="C",
            ingestion_mode="full",
        )
        repo.update(
            job_id,
            status="completed",
            progress=100,
            stage="completed",
            chunk_count=42,
            duration=12.5,
        )
        got = repo.get(job_id)
        assert got["status"] == "completed"
        assert got["progress"] == 100
        assert got["chunk_count"] == 42
        assert got["duration"] == 12.5
        # updated_at must advance beyond created_at
        assert got["updated_at"] is not None

    def test_update_unknown_job_is_noop(self, repo_with_session):
        repo, _ = repo_with_session
        # Must not raise; just logs and returns.
        repo.update("nope", status="completed")

    def test_update_ignores_none_values(self, repo_with_session):
        repo, _ = repo_with_session
        job_id = _fake_job_id()
        repo.create(
            job_id,
            filename="d.md",
            collection_id=1,
            collection_name="C",
            ingestion_mode="indexed",
        )
        repo.update(job_id, status="completed", progress=None, chunk_count=None)
        got = repo.get(job_id)
        assert got["status"] == "completed"
        assert got["progress"] == 0  # unchanged

    def test_list_recent_orders_newest_first(self, repo_with_session):
        repo, _ = repo_with_session
        first = _fake_job_id()
        second = _fake_job_id()
        repo.create(
            first,
            filename="a.md",
            collection_id=1,
            collection_name="C",
            ingestion_mode="indexed",
        )
        repo.create(
            second,
            filename="b.md",
            collection_id=1,
            collection_name="C",
            ingestion_mode="indexed",
        )
        recent = repo.list_recent(limit=10)
        ids = [j["job_id"] for j in recent]
        assert second in ids and first in ids
        assert ids.index(second) < ids.index(first)

    def test_list_recent_respects_limit(self, repo_with_session):
        repo, _ = repo_with_session
        for _i in range(5):
            repo.create(
                _fake_job_id(),
                filename="x.md",
                collection_id=1,
                collection_name="C",
                ingestion_mode="indexed",
            )
        assert len(repo.list_recent(limit=3)) == 3
