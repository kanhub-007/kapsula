"""Tests for SqlDocumentRepository — save_document returns copy, not mutation."""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kapsula.core.domain.entities.account import Account as DomainAccount
from kapsula.core.domain.entities.collection import Collection as DomainCollection
from kapsula.core.domain.entities.document import Document as DomainDocument
from kapsula.infrastructure.data.connection import Base
from kapsula.infrastructure.data.tables.account import Account as OrmAccount
from kapsula.infrastructure.data.tables.collection import Collection as OrmCollection
from kapsula.infrastructure.data.tables.document import Document as OrmDocument


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database with all tables."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def account(db_session: Session) -> DomainAccount:
    """Create a real Account in the in-memory DB via the ORM."""
    orm = OrmAccount(
        account_id=str(uuid.uuid4()), name="test-account", ip_address="127.0.0.1"
    )
    db_session.add(orm)
    db_session.commit()
    db_session.refresh(orm)
    return DomainAccount(
        id=orm.id,
        account_id=orm.account_id,
        name=orm.name,
        created_at=orm.created_at,
        ip_address=orm.ip_address,
    )


@pytest.fixture
def collection(db_session: Session, account: DomainAccount) -> DomainCollection:
    """Create a real Collection in the in-memory DB via the ORM, linked to an account."""
    orm = OrmCollection(
        collection_id=str(uuid.uuid4()),
        account_id=account.id,
        name="test-collection",
        ip_address="127.0.0.1",
    )
    db_session.add(orm)
    db_session.commit()
    db_session.refresh(orm)
    return DomainCollection(
        id=orm.id,
        collection_id=orm.collection_id,
        account_id=orm.account_id,
        name=orm.name,
        created_at=orm.created_at,
        ip_address=orm.ip_address,
    )


# ── Scenario 1: save_document returns new entity, original unchanged ──


class TestSaveDocumentReturnsCopy:
    """save_document MUST return a new DomainDocument with populated id,
    leaving the original input unchanged."""

    def test_returns_copy_with_populated_id(
        self, db_session: Session, collection: DomainCollection
    ):
        """Arrange — real repo, real in-memory SQLite DB."""
        from kapsula.infrastructure.repositories.data.sql_document_repository import (
            SqlDocumentRepository,
        )

        repo = SqlDocumentRepository()
        original = DomainDocument(
            job_id=str(uuid.uuid4()),
            collection_id=collection.id,
            filename="test.md",
            size=100,
            content="# Hello",
        )

        # Act
        result = repo.save_document(db_session, original)

        # Assert — outcome, not interaction
        assert result is not None, "save_document must return the persisted entity"
        assert isinstance(result, DomainDocument)
        assert result.id is not None, "returned entity must have a DB-generated id"
        assert isinstance(result.id, int), "id must be an integer"

    def test_original_is_not_mutated(
        self, db_session: Session, collection: DomainCollection
    ):
        """The input domain entity MUST NOT have its id field mutated."""
        from kapsula.infrastructure.repositories.data.sql_document_repository import (
            SqlDocumentRepository,
        )

        repo = SqlDocumentRepository()
        original = DomainDocument(
            job_id=str(uuid.uuid4()),
            collection_id=collection.id,
            filename="test.md",
            size=100,
            content="# Hello",
        )

        # Act
        repo.save_document(db_session, original)

        # Assert — original MUST still have id=None
        assert (
            original.id is None
        ), "save_document must NOT mutate the input entity's id"

    def test_returned_copy_preserves_other_fields(
        self, db_session: Session, collection: DomainCollection
    ):
        """The returned copy must have the same job_id, filename, etc. as the input."""
        from kapsula.infrastructure.repositories.data.sql_document_repository import (
            SqlDocumentRepository,
        )

        repo = SqlDocumentRepository()
        job_id = str(uuid.uuid4())
        original = DomainDocument(
            job_id=job_id,
            collection_id=collection.id,
            filename="preserve-me.md",
            size=2048,
            content="Some content",
        )

        # Act
        result = repo.save_document(db_session, original)

        # Assert — fields preserved, only id changed
        assert result.job_id == job_id
        assert result.filename == "preserve-me.md"
        assert result.size == 2048
        assert result.content == "Some content"
        assert result.collection_id == collection.id

    def test_persisted_row_matches_returned_entity(
        self, db_session: Session, collection: DomainCollection
    ):
        """The DB row must have the same id and job_id as the returned entity."""
        from kapsula.infrastructure.repositories.data.sql_document_repository import (
            SqlDocumentRepository,
        )

        repo = SqlDocumentRepository()
        job_id = str(uuid.uuid4())
        original = DomainDocument(
            job_id=job_id,
            collection_id=collection.id,
            filename="db-match.md",
            size=512,
            content="DB match test",
        )

        # Act
        result = repo.save_document(db_session, original)

        # Assert — query DB directly, verify row exists with same id
        orm_doc = (
            db_session.query(OrmDocument).filter(OrmDocument.job_id == job_id).first()
        )
        assert orm_doc is not None, "document row must exist in DB"
        assert orm_doc.id == result.id
        assert orm_doc.job_id == job_id
        assert orm_doc.filename == "db-match.md"
