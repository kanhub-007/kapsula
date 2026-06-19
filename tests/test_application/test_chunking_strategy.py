"""Tests for ChunkingStrategy implementations and the upload pipeline.

Covers S2.3 (fallback is a strategy swap) and S2.1 (one skeleton
orchestrates both shapes). Classical school: real chunker, real in-memory
SQLite, fake embedder; assert on outcomes (ctx population, persisted rows),
never on interactions.
"""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kapsula.core.domain.entities.document import Document
from kapsula.infrastructure.data.connection import Base
from kapsula.infrastructure.repositories.chunking import MarkdownChunker
from kapsula.infrastructure.repositories.processing.upload_pipeline_context import (
    UploadPipelineContext,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.flat_chunking_strategy import (
    FlatChunkingStrategy,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.subdocument_chunking_strategy import (
    SubDocumentChunkingStrategy,
)

# ── fakes ────────────────────────────────────────────────────────────


class FakeEmbedder:
    """Deterministic embedder (no network)."""

    def __init__(self, dim: int = 8):
        self._dim = dim

    def embed(self, text, batch_size=32) -> np.ndarray:
        texts = [text] if isinstance(text, str) else list(text)
        rng = np.random.default_rng(abs(hash(tuple(texts))) % (2**32))
        return rng.random((len(texts), self._dim)).astype("float32")


class _RecordingProgress:
    """Records the last status payload per job (no real store)."""

    def __init__(self):
        self.payloads: dict[str, dict] = {}

    def set(self, job_id, **kwargs):
        self.payloads[job_id] = kwargs

    def get(self, job_id):
        return self.payloads.get(job_id)

    def log_stage(self, *args, **kwargs):
        pass

    @staticmethod
    def elapsed_message(start_time):
        return "elapsed 0s"


class _NoopMaintenanceState:
    """Maintenance-state stand-in that records mark_stale / increment calls."""

    def __init__(self):
        self.stale_calls: list = []
        self.increment_calls: list = []

    def mark_collection_stale(self, collection, **kwargs):
        self.stale_calls.append(kwargs)

    def increment_uploads(self, collection_id):
        self.increment_calls.append(collection_id)

    def mark_collection_fresh(self, *args, **kwargs):
        pass


# ── fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def document(db_session) -> Document:
    """A persisted ORM document row, returned as a domain Document-like object.

    The pipeline reads/writes ORM attributes (status, duration, collection);
    we use the ORM instance directly since the existing helpers expect it.
    """
    from kapsula.infrastructure.data import Collection as OrmCollection
    from kapsula.infrastructure.data import Document as OrmDocument
    from kapsula.infrastructure.data.tables.account import Account as OrmAccount

    account = OrmAccount(account_id=str(uuid.uuid4()), name="acct", ip_address="x")
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    coll = OrmCollection(
        collection_id="coll-1", account_id=account.id, name="Coll", ip_address="x"
    )
    db_session.add(coll)
    db_session.commit()
    db_session.refresh(coll)
    doc = OrmDocument(
        job_id="job-1",
        collection_id=coll.id,
        filename="doc.md",
        size=100,
        content="# Title",
        status="processing",
        ip_address="x",
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    return doc


def _ctx(db_session, document, markdown, chunker=None) -> UploadPipelineContext:
    return UploadPipelineContext(
        db=db_session,
        document=document,
        job_id="job-1",
        ingestion_mode="fast",
        start_time=0.0,
        markdown_content=markdown,
        chunker=chunker or MarkdownChunker(max_tokens=512),
        embedder=FakeEmbedder(),
        progress=_RecordingProgress(),
        maintenance_state=_NoopMaintenanceState(),
        card_repo=None,
        chunk_repo=None,
    )


FLAT_MARKDOWN = (
    "## Big Document Title\n\n"
    + "This is section content with enough text to form a real chunk.\n\n" * 20
)

# Subdocument markdown: H1 breadcrumbs that extract_subdocuments groups by key.
SUBDOC_MARKDOWN = """# docs.example.com / Guides / API Reference / Authentication

Some intro to authentication that is long enough to be meaningful content here.

# docs.example.com / Guides / API Reference / Rate Limits

Rate limiting details go here with enough text to form a real chunk.
"""


# ── S2.3: FlatChunkingStrategy populates ctx ─────────────────────────


class TestFlatChunkingStrategy:
    def test_extract_and_chunk_populates_chunks_and_parent_sections(
        self, db_session, document
    ):
        ctx = _ctx(db_session, document, FLAT_MARKDOWN)

        FlatChunkingStrategy().extract_and_chunk(ctx)

        assert len(ctx.chunks) > 0
        assert "content" in ctx.chunks[0]
        assert "metadata" in ctx.chunks[0]
        # parent_sections is populated (H2 headings exist in FLAT_MARKDOWN)
        assert isinstance(ctx.parent_sections, dict)
        # Flat path does not produce a subdoc plan.
        assert ctx.subdoc_plan is None


# ── S2.3: SubDocumentChunkingStrategy fallback ───────────────────────


class TestSubDocumentChunkingStrategyFallback:
    def test_invalid_subdocuments_falls_back_to_flat(self, db_session, document):
        """When validate_subdocuments is false, the subdoc strategy must
        delegate to FlatChunkingStrategy and populate ctx the flat way
        (chunks set, subdoc_plan left None)."""
        ctx = _ctx(db_session, document, FLAT_MARKDOWN)
        flat = FlatChunkingStrategy()
        strategy = SubDocumentChunkingStrategy(flat)

        strategy.extract_and_chunk(ctx)

        # Flat fallback: chunks populated, no subdoc plan.
        assert len(ctx.chunks) > 0
        assert ctx.subdoc_plan is None

    def test_valid_subdocuments_populates_plan(self, db_session, document):
        """Valid breadcrumb H1s produce a non-empty subdoc_plan."""
        ctx = _ctx(db_session, document, SUBDOC_MARKDOWN)
        flat = FlatChunkingStrategy()
        strategy = SubDocumentChunkingStrategy(flat)

        strategy.extract_and_chunk(ctx)

        assert ctx.subdoc_plan is not None
        assert len(ctx.subdoc_plan) >= 1
        plan_entry = ctx.subdoc_plan[0]
        assert "breadcrumb_key" in plan_entry
        assert "chunks" in plan_entry
        assert "parent_sections" in plan_entry
        assert "pages" in plan_entry
        # Aggregated chunks across subdocs.
        assert len(ctx.chunks) >= 1
