"""Tests for UploadPipelineContext — the mutable carrier DTO.

Black-box (S1.2): the context carries every dependency and intermediate
result so pipeline step methods have <=6 parameters (no long-parameter-list
smell). Asserts on construction, defaults, and mutability — never on
interactions, since the context has no behaviour.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from kapsula.core.application.dto.upload_pipeline_context import (
    UploadPipelineContext,
)
from kapsula.core.domain.entities.document import Document
from kapsula.core.domain.entities.sub_document import SubDocument

# ── lightweight stand-ins for injected infrastructure deps ──────────
# The context is a pure carrier; it never calls these, so simple sentinels
# suffice (Classical school: real objects where they have behaviour; plain
# sentinels where the SUT only holds a reference).


class _Sentinel:
    """A unique marker object used as a stand-in for an injected dep."""


@pytest.fixture
def document() -> Document:
    return Document(id=1, job_id="job-1", filename="doc.md")


class TestUploadPipelineContextFields:
    """The context must carry every field listed in 03-domain.md."""

    def test_carries_all_documented_fields(self):
        expected = {
            "db",
            "document",
            "job_id",
            "ingestion_mode",
            "start_time",
            "markdown_content",
            "chunker",
            "embedder",
            "progress",
            "maintenance_state",
            "card_repo",
            "chunk_repo",
            "structure",
            "parent_sections",
            "chunks",
            "subdocs",
            "subdoc_plan",
            "duration",
        }
        actual = {f.name for f in fields(UploadPipelineContext)}
        assert actual == expected, (
            f"Context fields mismatch. Missing: {expected - actual}. "
            f"Extra: {actual - expected}"
        )

    def test_construct_with_dependencies(self, document: Document):
        chunker = _Sentinel()
        embedder = _Sentinel()
        progress = _Sentinel()
        maintenance = _Sentinel()
        card_repo = _Sentinel()
        chunk_repo = _Sentinel()
        db = _Sentinel()

        ctx = UploadPipelineContext(
            db=db,
            document=document,
            job_id="job-1",
            ingestion_mode="indexed",
            start_time=100.0,
            markdown_content="# Title\n\nbody",
            chunker=chunker,
            embedder=embedder,
            progress=progress,
            maintenance_state=maintenance,
            card_repo=card_repo,
            chunk_repo=chunk_repo,
        )

        # Every dependency is retrievable unchanged.
        assert ctx.db is db
        assert ctx.document is document
        assert ctx.job_id == "job-1"
        assert ctx.ingestion_mode == "indexed"
        assert ctx.start_time == 100.0
        assert ctx.markdown_content == "# Title\n\nbody"
        assert ctx.chunker is chunker
        assert ctx.embedder is embedder
        assert ctx.progress is progress
        assert ctx.maintenance_state is maintenance
        assert ctx.card_repo is card_repo
        assert ctx.chunk_repo is chunk_repo


class TestUploadPipelineContextIntermediates:
    """Intermediate results default empty and are mutable in place."""

    def test_intermediates_default_empty(self, document: Document):
        ctx = UploadPipelineContext(
            db=_Sentinel(),
            document=document,
            job_id="job-1",
            ingestion_mode="fast",
            start_time=0.0,
            markdown_content="",
            chunker=_Sentinel(),
            embedder=_Sentinel(),
            progress=_Sentinel(),
            maintenance_state=_Sentinel(),
            card_repo=_Sentinel(),
            chunk_repo=_Sentinel(),
        )

        assert ctx.structure is None
        assert ctx.parent_sections == {}
        assert ctx.chunks == []
        assert ctx.subdocs is None
        assert ctx.duration is None

    def test_steps_can_write_intermediates(self, document: Document):
        ctx = UploadPipelineContext(
            db=_Sentinel(),
            document=document,
            job_id="job-1",
            ingestion_mode="indexed",
            start_time=0.0,
            markdown_content="",
            chunker=_Sentinel(),
            embedder=_Sentinel(),
            progress=_Sentinel(),
            maintenance_state=_Sentinel(),
            card_repo=_Sentinel(),
            chunk_repo=_Sentinel(),
        )

        # extract_structure step writes the skeleton
        ctx.structure = "# Skeleton"
        # chunking step writes chunks + parent_sections
        ctx.chunks = [{"content": "c1"}, {"content": "c2"}]
        ctx.parent_sections = {"sec1": {"title": "Sec 1"}}
        # subdocument chunking writes subdocs
        ctx.subdocs = [SubDocument(id=10, breadcrumb_key="ch1")]
        # finalize step writes duration
        ctx.duration = 12.5

        assert ctx.structure == "# Skeleton"
        assert len(ctx.chunks) == 2
        assert ctx.parent_sections["sec1"]["title"] == "Sec 1"
        assert ctx.subdocs[0].breadcrumb_key == "ch1"
        assert ctx.duration == 12.5
