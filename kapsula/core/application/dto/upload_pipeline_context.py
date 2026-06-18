"""DTO: mutable carrier for one upload pipeline run.

Carries every dependency and intermediate result so pipeline step methods
have <=6 parameters (closes the long-parameter-list smell flagged in the
upload-pipeline-refactor spec, scenario S1.2).

The context is a pure data carrier — no behaviour. Steps read inputs from
it and write intermediates back to it. Lifecycle of the ``db`` session is
owned by the presentation adapter (``tasks.py``), NOT by the context or
the pipeline.

Types follow the project convention used by the domain repository
interfaces: ``db`` and infrastructure deps are ``Any`` to avoid importing
SQLAlchemy / concrete infrastructure classes into the application layer.
Domain types (``Document``, ``SubDocument``, ``Chunker``, ``Embedder``)
are typed explicitly because they live in the domain layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kapsula.core.domain.entities.document import Document
from kapsula.core.domain.entities.sub_document import SubDocument
from kapsula.core.domain.interfaces.chunker import Chunker
from kapsula.core.domain.interfaces.embedder import Embedder


@dataclass
class UploadPipelineContext:
    """Mutable carrier for a single upload pipeline run.

    Dependencies (injected once at construction):
        db, document, job_id, ingestion_mode, start_time, markdown_content,
        chunker, embedder, progress, maintenance_state, card_repo, chunk_repo.

    Intermediates (written by steps during ``UploadPipeline.run``):
        structure, parent_sections, chunks, subdocs, duration.
    """

    # ── injected dependencies ────────────────────────────────
    db: Any
    document: Document
    job_id: str
    ingestion_mode: str
    start_time: float
    markdown_content: str
    chunker: Chunker
    embedder: Embedder
    progress: Any
    maintenance_state: Any
    card_repo: Any
    chunk_repo: Any

    # ── intermediates (set by steps) ─────────────────────────
    structure: str | None = None
    parent_sections: dict = field(default_factory=dict)
    chunks: list[dict] = field(default_factory=list)
    subdocs: list[SubDocument] | None = None
    duration: float | None = None
