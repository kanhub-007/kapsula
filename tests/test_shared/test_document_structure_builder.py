"""Tests for the shared document structure builder."""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kapsula.infrastructure.data.connection import Base
from kapsula.infrastructure.data.tables.account import Account as OrmAccount
from kapsula.infrastructure.data.tables.collection import Collection as OrmCollection
from kapsula.infrastructure.data.tables.document import Document as OrmDocument
from kapsula.infrastructure.data.tables.library_card import LibraryCard
from kapsula.infrastructure.data.tables.sub_document import SubDocument
from kapsula.presentation.shared.document_structure_builder import (
    build_document_structure_from_subdocs,
    build_document_structure_from_document,
)


@pytest.fixture
def db_session():
    """In-memory SQLite database with all tables."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Sess = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Sess()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def seeded_db(db_session: Session):
    """Create account, collection, document, sub-documents, and library cards."""
    account = OrmAccount(account_id=str(uuid.uuid4()), name="test", ip_address="127.0.0.1")
    db_session.add(account)
    db_session.commit()

    coll = OrmCollection(collection_id=str(uuid.uuid4()), account_id=account.id, name="Test", ip_address="127.0.0.1")
    db_session.add(coll)
    db_session.commit()

    doc = OrmDocument(job_id=str(uuid.uuid4()), collection_id=coll.id, filename="test.md", size=100, content="# Test", ip_address="127.0.0.1")
    db_session.add(doc)
    db_session.commit()

    # Sub-document 1
    sd1 = SubDocument(document_id=doc.id, breadcrumb_key="Chapter 1", breadcrumb_level=2, page_count=2)
    db_session.add(sd1)
    db_session.commit()

    # Library cards for sub-document 1
    cards_sd1 = [
        LibraryCard(collection_id=coll.id, document_id=doc.id, sub_document_id=sd1.id, doc_id="h1", level="level_1", title="H1 Title", content="h1"),
        LibraryCard(collection_id=coll.id, document_id=doc.id, sub_document_id=sd1.id, doc_id="h2a", level="level_2", title="H2 Section A", content="h2a"),
        LibraryCard(collection_id=coll.id, document_id=doc.id, sub_document_id=sd1.id, doc_id="h3", level="level_3", title="H3 Subsection", content="h3"),
    ]
    for c in cards_sd1:
        db_session.add(c)

    # Sub-document 2
    sd2 = SubDocument(document_id=doc.id, breadcrumb_key="Chapter 2", breadcrumb_level=2, page_count=1)
    db_session.add(sd2)
    db_session.commit()

    cards_sd2 = [
        LibraryCard(collection_id=coll.id, document_id=doc.id, sub_document_id=sd2.id, doc_id="h1b", level="level_1", title="H1 Another", content="h1b"),
    ]
    for c in cards_sd2:
        db_session.add(c)

    # Document-level library cards (for single-index test)
    cards_doc = [
        LibraryCard(collection_id=coll.id, document_id=doc.id, doc_id="d_h1", level="level_1", title="Doc H1", content="dh1"),
        LibraryCard(collection_id=coll.id, document_id=doc.id, doc_id="d_h2", level="level_2", title="Doc H2", content="dh2"),
    ]
    for c in cards_doc:
        db_session.add(c)
    db_session.commit()

    return {"account": account, "collection": coll, "document": doc, "subdocs": [sd1, sd2]}


# ── Scenario: Sub-document path produces correct structure ──


class TestBuildDocumentStructureFromSubdocs:
    """build_document_structure_from_subdocs tests."""

    def test_returns_correct_structure(self, db_session: Session, seeded_db: dict):
        """Should return a list of {subdocument_name, sections} dicts."""
        subdocs = seeded_db["subdocs"]
        result = build_document_structure_from_subdocs(subdocs, db_session)

        assert len(result) == 2

        # First sub-document
        assert result[0]["subdocument_name"] == "Chapter 1"
        assert len(result[0]["sections"]) == 3
        # Cards ordered by level.desc() → level_3 first, level_1 last
        assert result[0]["sections"][0]["level"] == "level_3"
        assert result[0]["sections"][0]["title"] == "H3 Subsection"
        assert result[0]["sections"][2]["level"] == "level_1"
        assert result[0]["sections"][2]["title"] == "H1 Title"

        # Second sub-document
        assert result[1]["subdocument_name"] == "Chapter 2"
        assert len(result[1]["sections"]) == 1

    def test_empty_subdocs_returns_empty(self, db_session: Session):
        """Empty subdoc list should return empty list."""
        result = build_document_structure_from_subdocs([], db_session)
        assert result == []

    def test_subdocs_without_cards_returned_empty(self, db_session: Session):
        """Sub-document with no library cards should not appear in result."""
        doc = OrmDocument(job_id=str(uuid.uuid4()), collection_id=1, filename="empty.md", size=10, content="", ip_address="127.0.0.1")
        db_session.add(doc)
        db_session.commit()
        sd = SubDocument(document_id=doc.id, breadcrumb_key="Empty", breadcrumb_level=2, page_count=0)
        db_session.add(sd)
        db_session.commit()

        result = build_document_structure_from_subdocs([sd], db_session)
        assert result == []


# ── Scenario: Single-index document path produces correct structure ──


class TestBuildDocumentStructureFromDocument:
    """build_document_structure_from_document tests."""

    def test_returns_single_element_list(self, db_session: Session, seeded_db: dict):
        """Should return a single-element list with the document name."""
        doc = seeded_db["document"]
        result = build_document_structure_from_document(doc.id, doc.filename, db_session)

        assert len(result) == 1
        assert result[0]["subdocument_name"] == "test.md"
        assert len(result[0]["sections"]) == 2

    def test_no_cards_returns_empty(self, db_session: Session):
        """Document without library cards should return empty list."""
        result = build_document_structure_from_document(99999, "nonexistent", db_session)
        assert result == []


# ── Scenario: Output format matches QueryPlanner contract ──


class TestOutputFormat:
    """Verify the output format matches what QueryPlanner expects."""

    def test_sections_have_required_keys(self, db_session: Session, seeded_db: dict):
        """Each section must have 'level' and 'title' keys."""
        subdocs = seeded_db["subdocs"]
        result = build_document_structure_from_subdocs(subdocs, db_session)

        for entry in result:
            assert isinstance(entry["subdocument_name"], str)
            for section in entry["sections"]:
                assert set(section.keys()) == {"level", "title"}
                assert section["level"] in ("level_1", "level_2", "level_3")
                assert isinstance(section["title"], str)
                assert len(section["title"]) > 0
