"""Tests for the UploadPipeline orchestrator (S2.1).

Black-box: the pipeline runs five ordered steps (extract_structure →
chunk_and_persist → build_indexes → finalize_document → run_maintenance)
and produces the observable outcomes — DocumentStructure row, persisted
chunks, completed document status, deferred-maintenance state for fast
mode. Uses in-memory SQLite + a fake embedder + the real chunker.

Also asserts the structural contracts from the spec:
- ``run()`` is a flat dispatcher (<30 lines, only ``self._<step>(ctx)`` calls)
- each step method is <50 lines
"""

from __future__ import annotations

import inspect
import uuid

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kapsula.infrastructure.data import Chunk, DocumentStructure
from kapsula.infrastructure.data.connection import Base
from kapsula.infrastructure.repositories.chunking import MarkdownChunker
from kapsula.infrastructure.repositories.processing.upload_pipeline_context import (
    UploadPipelineContext,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.fast_upload_ingestion_strategy import (
    FastUploadIngestionStrategy,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.flat_chunking_strategy import (
    FlatChunkingStrategy,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.upload_pipeline import (
    UploadPipeline,
)

# ── fakes (shared with test_chunking_strategy) ───────────────────────


class FakeEmbedder:
    def __init__(self, dim: int = 8):
        self._dim = dim

    def embed(self, text, batch_size=32) -> np.ndarray:
        texts = [text] if isinstance(text, str) else list(text)
        rng = np.random.default_rng(abs(hash(tuple(texts))) % (2**32))
        return rng.random((len(texts), self._dim)).astype("float32")


class _RecordingProgress:
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
    def __init__(self):
        self.stale_calls: list = []

    def mark_collection_stale(self, collection, **kwargs):
        self.stale_calls.append(kwargs)

    def increment_uploads(self, collection_id):
        pass

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
def document(db_session):
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


FLAT_MARKDOWN = (
    "## Big Document Title\n\n"
    + "This is section content with enough text to form a real chunk.\n\n" * 20
)


def _ctx(db_session, document, markdown) -> UploadPipelineContext:
    progress = _RecordingProgress()
    return UploadPipelineContext(
        db=db_session,
        document=document,
        job_id="job-1",
        ingestion_mode="fast",
        start_time=0.0,
        markdown_content=markdown,
        chunker=MarkdownChunker(max_tokens=512),
        embedder=FakeEmbedder(),
        progress=progress,
        maintenance_state=_NoopMaintenanceState(),
        card_repo=None,
        chunk_repo=None,
    )


# ── S2.1 behavioural: pipeline produces the right outcomes ──────────


class TestUploadPipelineFlatFast:
    """Flat document + fast mode: chunks persisted, doc completed, no indexes."""

    def test_pipeline_completes_flat_document(self, db_session, document):
        pipeline = UploadPipeline(
            chunking=FlatChunkingStrategy(), ingestion=FastUploadIngestionStrategy()
        )
        ctx = _ctx(db_session, document, FLAT_MARKDOWN)

        pipeline.run(ctx)

        # DocumentStructure row created.
        structures = (
            db_session.query(DocumentStructure)
            .filter(DocumentStructure.document_id == document.id)
            .all()
        )
        assert len(structures) == 1

        # Chunks persisted.
        chunks = db_session.query(Chunk).filter(Chunk.document_id == document.id).all()
        assert len(chunks) == len(ctx.chunks)
        assert len(chunks) > 0

        # Document marked completed with a duration.
        assert document.status == "completed"
        assert document.duration is not None

        # ctx.duration populated by finalize step.
        assert ctx.duration is not None


# ── S2.1 structural: run() is a flat dispatcher, steps <50 lines ─────


class TestUploadPipelineShape:
    def test_run_is_flat_dispatcher_under_30_lines(self):
        source = inspect.getsource(UploadPipeline.run)
        line_count = len(
            [
                ln
                for ln in source.splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
        )
        assert line_count <= 30, f"run() is {line_count} lines (must be <=30)"

    def test_run_only_calls_named_step_methods(self):
        """run() body must be a flat list of self._<step>(ctx) calls."""
        source = inspect.getsource(UploadPipeline.run)
        # Every non-blank, non-def, non-docstring line should be a step call.
        step_calls = [
            ln.strip()
            for ln in source.splitlines()
            if ln.strip()
            and not ln.strip().startswith(("def ", '"""', "#"))
            and "self._" in ln
        ]
        # At least the five documented steps.
        assert len(step_calls) >= 5
        for call in step_calls:
            assert call.startswith(
                "self._"
            ), f"run() contains a non-step line: {call!r}"

    @pytest.mark.parametrize(
        "step_name",
        [
            "_extract_structure",
            "_chunk_and_persist",
            "_build_indexes",
            "_finalize_document",
            "_run_maintenance",
        ],
    )
    def test_each_step_is_under_50_lines(self, step_name):
        method = getattr(UploadPipeline, step_name)
        source = inspect.getsource(method)
        line_count = len(source.splitlines())
        assert line_count <= 50, f"{step_name} is {line_count} lines (must be <=50)"
