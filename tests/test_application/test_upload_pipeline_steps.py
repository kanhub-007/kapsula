"""Slice 4 — step-level unit tests for the upload pipeline (S4.1).

Each pipeline step is exercised in isolation with in-memory SQLite +
FakeEmbedder + temp DATA_DIR. Asserts on observable outcomes (rows,
files, state), never on interactions.

S4.2 (per-mode regression) lives in test_upload_exactly_once.py.
"""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kapsula.infrastructure.data import (
    Chunk,
    DocumentStructure,
    SubDocument,
)
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
from kapsula.infrastructure.repositories.processing.upload_strategies.indexed_upload_ingestion_strategy import (
    IndexedUploadIngestionStrategy,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.subdocument_chunking_strategy import (
    SubDocumentChunkingStrategy,
)
from kapsula.infrastructure.repositories.processing.upload_strategies.upload_pipeline import (
    UploadPipeline,
)

# ── fakes ────────────────────────────────────────────────────────────


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


class _RecordingMaintenanceState:
    def __init__(self):
        self.stale_marked = False
        self.incremented = False

    def mark_collection_stale(self, collection, **kwargs):
        self.stale_marked = True

    def increment_uploads(self, collection_id):
        self.incremented = True

    def mark_collection_fresh(self, *args, **kwargs):
        pass


# ── fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp DATA_DIR + in-memory SQLite; patches the connection module."""
    import kapsula.infrastructure.data.connection as conn

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(conn, "DATA_DIR", str(data_dir))
    db = Session()
    try:
        yield {"db": db, "data_dir": data_dir}
    finally:
        db.close()


@pytest.fixture
def document(env):
    from kapsula.infrastructure.data import Collection as OrmCollection
    from kapsula.infrastructure.data import Document as OrmDocument
    from kapsula.infrastructure.data.tables.account import Account as OrmAccount

    account = OrmAccount(account_id=str(uuid.uuid4()), name="acct", ip_address="x")
    env["db"].add(account)
    env["db"].commit()
    env["db"].refresh(account)
    coll = OrmCollection(
        collection_id="coll-1", account_id=account.id, name="Coll", ip_address="x"
    )
    env["db"].add(coll)
    env["db"].commit()
    env["db"].refresh(coll)
    doc = OrmDocument(
        job_id="job-1",
        collection_id=coll.id,
        filename="doc.md",
        size=100,
        content="# Title",
        status="processing",
        ip_address="x",
    )
    env["db"].add(doc)
    env["db"].commit()
    env["db"].refresh(doc)
    return doc


def _ctx(env, document, markdown, mode="fast") -> UploadPipelineContext:
    return UploadPipelineContext(
        db=env["db"],
        document=document,
        job_id="job-1",
        ingestion_mode=mode,
        start_time=0.0,
        markdown_content=markdown,
        chunker=MarkdownChunker(max_tokens=512),
        embedder=FakeEmbedder(),
        progress=_RecordingProgress(),
        maintenance_state=_RecordingMaintenanceState(),
        card_repo=None,
        chunk_repo=None,
    )


FLAT_MARKDOWN = (
    "## Section Title\n\n"
    + "Enough body text to form a real chunk here yes indeed.\n\n" * 20
)

SUBDOC_MARKDOWN = """# docs.example.com / Guides / API / Auth

Intro to auth with enough text to chunk meaningfully here.

# docs.example.com / Guides / API / Limits

Rate limit details with enough text to chunk meaningfully here.
"""


def _count_index_files(data_dir) -> tuple[int, int]:
    """Count FAISS (.index) and BM25 (.pkl) files under data_dir."""
    faiss = 0
    bm25 = 0
    for path in data_dir.rglob("*"):
        if path.suffix == ".index":
            faiss += 1
        elif path.suffix == ".pkl":
            bm25 += 1
    return faiss, bm25


# ── S4.1: extract_structure ──────────────────────────────────────────


class TestExtractStructureStep:
    def test_writes_one_document_structure_row(self, env, document):
        pipeline = UploadPipeline(FlatChunkingStrategy(), FastUploadIngestionStrategy())
        ctx = _ctx(env, document, FLAT_MARKDOWN)

        pipeline._extract_structure(ctx)

        rows = (
            env["db"]
            .query(DocumentStructure)
            .filter(DocumentStructure.document_id == document.id)
            .all()
        )
        assert len(rows) == 1
        assert ctx.structure is not None


# ── S4.1: chunk_and_persist (flat) ───────────────────────────────────


class TestChunkAndPersistFlatStep:
    def test_chunk_rows_match_chunker_output(self, env, document):
        pipeline = UploadPipeline(FlatChunkingStrategy(), FastUploadIngestionStrategy())
        ctx = _ctx(env, document, FLAT_MARKDOWN)

        pipeline._extract_structure(ctx)
        pipeline._chunk_and_persist(ctx)

        chunks = env["db"].query(Chunk).filter(Chunk.document_id == document.id).all()
        assert len(chunks) == len(ctx.chunks)
        assert len(chunks) > 0


# ── S4.1: chunk_and_persist (subdocument) ────────────────────────────


class TestChunkAndPersistSubdocumentStep:
    def test_one_subdocument_per_breadcrumb_with_linked_chunks(self, env, document):
        pipeline = UploadPipeline(
            SubDocumentChunkingStrategy(), FastUploadIngestionStrategy()
        )
        ctx = _ctx(env, document, SUBDOC_MARKDOWN)

        pipeline._extract_structure(ctx)
        pipeline._chunk_and_persist(ctx)

        subdocs = (
            env["db"]
            .query(SubDocument)
            .filter(SubDocument.document_id == document.id)
            .all()
        )
        assert len(subdocs) == len(ctx.subdoc_plan)
        assert len(subdocs) >= 1
        # Each subdocument has linked chunks.
        for sd in subdocs:
            sd_chunks = (
                env["db"].query(Chunk).filter(Chunk.sub_document_id == sd.id).all()
            )
            assert len(sd_chunks) > 0


# ── S4.1: build_indexes ──────────────────────────────────────────────


class TestBuildIndexesStep:
    def test_fast_mode_writes_zero_index_files(self, env, document):
        pipeline = UploadPipeline(FlatChunkingStrategy(), FastUploadIngestionStrategy())
        ctx = _ctx(env, document, FLAT_MARKDOWN, mode="fast")
        pipeline._extract_structure(ctx)
        pipeline._chunk_and_persist(ctx)

        pipeline._build_indexes(ctx)

        faiss, bm25 = _count_index_files(env["data_dir"])
        assert faiss == 0
        assert bm25 == 0

    def test_indexed_flat_writes_one_faiss_and_one_bm25(self, env, document):
        pipeline = UploadPipeline(
            FlatChunkingStrategy(), IndexedUploadIngestionStrategy()
        )
        ctx = _ctx(env, document, FLAT_MARKDOWN, mode="indexed")
        pipeline._extract_structure(ctx)
        pipeline._chunk_and_persist(ctx)

        pipeline._build_indexes(ctx)

        faiss, bm25 = _count_index_files(env["data_dir"])
        assert faiss >= 1
        assert bm25 >= 1


# ── S4.1: run_maintenance ────────────────────────────────────────────


class TestRunMaintenanceStep:
    def test_fast_mode_marks_state_stale(self, env, document):
        pipeline = UploadPipeline(FlatChunkingStrategy(), FastUploadIngestionStrategy())
        ctx = _ctx(env, document, FLAT_MARKDOWN, mode="fast")
        pipeline._extract_structure(ctx)
        pipeline._chunk_and_persist(ctx)

        pipeline._run_maintenance(ctx)

        assert ctx.maintenance_state.stale_marked is True
        assert ctx.maintenance_state.incremented is True

    def test_indexed_mode_marks_state_stale(self, env, document):
        pipeline = UploadPipeline(
            FlatChunkingStrategy(), IndexedUploadIngestionStrategy()
        )
        ctx = _ctx(env, document, FLAT_MARKDOWN, mode="indexed")
        pipeline._extract_structure(ctx)
        pipeline._chunk_and_persist(ctx)

        pipeline._run_maintenance(ctx)

        assert ctx.maintenance_state.stale_marked is True
